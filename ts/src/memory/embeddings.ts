export class EmbeddingUnavailableError extends Error {
  constructor(message: string, options?: ErrorOptions) {
    super(message, options);
    this.name = "EmbeddingUnavailableError";
  }
}

export interface EmbeddingProvider {
  name: string;
  model: string;
  dimensions: number | null;
  embedPassages(texts: string[]): Promise<number[][]>;
  embedQuery(text: string): Promise<number[]>;
}

export function packVector(vector: number[]): Uint8Array {
  const buffer = new ArrayBuffer(vector.length * 4);
  const view = new DataView(buffer);
  vector.forEach((value, index) => view.setFloat32(index * 4, value, true));
  return new Uint8Array(buffer);
}

export function unpackVector(blob: Uint8Array, dimensions: number): number[] {
  if (blob.byteLength % 4 !== 0) {
    throw new Error("Vector blob length is not divisible by 4");
  }
  const actual = blob.byteLength / 4;
  if (actual !== dimensions) {
    throw new Error(`Vector blob has ${actual} dimensions; expected ${dimensions}`);
  }
  const view = new DataView(blob.buffer, blob.byteOffset, blob.byteLength);
  return Array.from({ length: dimensions }, (_, index) => view.getFloat32(index * 4, true));
}

export function cosineSimilarity(left: number[], right: number[]): number {
  if (left.length !== right.length) {
    throw new Error(`Vector dimensions differ: ${left.length} != ${right.length}`);
  }
  let dot = 0;
  let leftNorm = 0;
  let rightNorm = 0;
  for (let index = 0; index < left.length; index += 1) {
    dot += left[index]! * right[index]!;
    leftNorm += left[index]! ** 2;
    rightNorm += right[index]! ** 2;
  }
  if (leftNorm === 0 || rightNorm === 0) return 0;
  return dot / (Math.sqrt(leftNorm) * Math.sqrt(rightNorm));
}

async function dynamicImport(specifier: string): Promise<Record<string, unknown>> {
  const importer = new Function("specifier", "return import(specifier)") as (
    specifier: string,
  ) => Promise<Record<string, unknown>>;
  return importer(specifier);
}

export class TransformersJsProvider implements EmbeddingProvider {
  readonly name = "transformers-js";
  dimensions: number | null = null;
  private extractor: unknown = null;

  constructor(readonly model: string) {}

  private async load(): Promise<unknown> {
    if (this.extractor) return this.extractor;
    let module: Record<string, unknown>;
    try {
      module = await dynamicImport("@huggingface/transformers");
    } catch (error) {
      throw new EmbeddingUnavailableError(
        "@huggingface/transformers is not installed; install it to enable semantic memory",
        { cause: error },
      );
    }

    try {
      const pipeline = module.pipeline as (
        task: string,
        model: string,
        options: Record<string, unknown>,
      ) => Promise<unknown>;
      this.extractor = await pipeline("feature-extraction", this.model, {
        dtype: "fp32",
      });
    } catch (error) {
      throw new EmbeddingUnavailableError(
        `Embedding model is not available: ${this.model}`,
        { cause: error },
      );
    }
    return this.extractor;
  }

  private async embed(texts: string[]): Promise<number[][]> {
    if (!texts.length) return [];
    const extractor = (await this.load()) as (
      input: string[],
      options: Record<string, unknown>,
    ) => Promise<{ tolist(): number[][][] | number[][] }>;
    const output = await extractor(texts, { pooling: "mean", normalize: true });
    const raw = output.tolist() as number[] | number[][];
    const matrix =
      Array.isArray(raw[0]) && typeof (raw[0] as number[])[0] === "number"
        ? (raw as number[][])
        : [raw as number[]];
    if (matrix[0]) this.dimensions = matrix[0].length;
    return matrix;
  }

  async embedPassages(texts: string[]): Promise<number[][]> {
    return this.embed(texts);
  }

  async embedQuery(text: string): Promise<number[]> {
    const [vector] = await this.embed([text]);
    return vector ?? [];
  }
}
