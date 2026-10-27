const MAX_CUES = 12;
const MAX_CUE_LENGTH = 80;

const BACKTICK_RE = /`([^`]{1,120})`/g;
const QUOTE_RE = /"([^"]{1,120})"/g;
const PATH_RE = /(?<!\w)[\w./@+-]+\.[A-Za-z0-9]{1,8}(?!\w)/g;
const SENTENCE_RE = /[^.!?。！？\n]+/g;
const SEPARATOR_RE = /\s+(?:for|in|on|about|with|when|where|because)\s+/;

const LEADING_CONTEXT_PATTERNS = [
  /^users?\s+(?:prefer|prefers|preferred|like|likes|want|wants|use|uses|need|needs)\s+/,
  /^prefer\s+/,
  /^use\s+/,
  /^(?:is|are|was|were)\s+/,
  /^we\s+decided\s+(?:that\s+)?/,
  /^decided\s+(?:that\s+)?/,
  /^remember\s+(?:that\s+)?/,
  /^always\s+(?:run|use|keep|write|prefer|choose|call)\s+/,
  /^always\s+/,
  /^never\s+(?:run|use|keep|write|prefer|choose|call)?\s*/,
];

const QUERY_PREFIX_RE =
  /^(?:where|what|which|how|why|when)\s+(?:(?:is|are|was|were|did|do|does|should|must)\s+)?/;
const TRAILING_CLAUSE_RE = /\s+(?:are|is|was|were|will be|should be|must be)\s+/;
const MODAL_CLAUSE_RE = /\s+(?:must|should|needs? to|has to)\s+/;
const LEADING_VERB_RE =
  /^(?:emit|use|run|keep|write|prefer|choose|call|store|rebuild|delete|create)\s+(?:an?\s+|the\s+)?/;

const QUERY_SUFFIX_WORDS = new Set(["decision", "memory", "policy", "preference", "requirement"]);
const GENERIC_TOPIC_SUFFIXES = new Set([
  "component",
  "components",
  "event",
  "events",
  "panel",
  "panels",
  "screen",
  "screens",
  "setting",
  "settings",
]);
const LOW_VALUE_WORDS = new Set([
  "a",
  "after",
  "an",
  "and",
  "for",
  "in",
  "of",
  "on",
  "or",
  "the",
  "to",
  "when",
  "where",
  "with",
]);

function cleanTerm(value: unknown): string {
  return String(value).trim().split(/\s+/).join(" ").slice(0, MAX_CUE_LENGTH).trimEnd();
}

export function normalizeCues(values: Iterable<unknown>, limit = MAX_CUES): string[] {
  const cues: string[] = [];
  const seen = new Set<string>();

  for (const value of values) {
    const cue = cleanTerm(value);
    const key = cue.toLowerCase();
    if (!cue || seen.has(key)) continue;
    cues.push(cue);
    seen.add(key);
    if (cues.length >= limit) break;
  }

  return cues;
}

function extractTerms(text: string): string[] {
  return [
    ...[...text.matchAll(BACKTICK_RE)].map((match) => match[1]!),
    ...[...text.matchAll(QUOTE_RE)].map((match) => match[1]!),
    ...[...text.matchAll(PATH_RE)].map((match) => match[0]),
  ];
}

function normalizePhraseText(value: string): string {
  const text = value
    .toLowerCase()
    .replaceAll("`", " ")
    .replaceAll('"', " ")
    .replaceAll("'", " ")
    .replace(/[^a-z0-9_./@+-]+/g, " ");
  return cleanTerm(text).replace(/^[ .:/-]+|[ .:/-]+$/g, "");
}

function stripLeadingContext(value: string): string {
  for (const pattern of LEADING_CONTEXT_PATTERNS) {
    if (pattern.test(value)) {
      return value.replace(pattern, "").trim();
    }
  }
  return value;
}

function trimQuerySuffix(value: string): string {
  const tokens = value.split(" ");
  while (tokens.length > 2 && QUERY_SUFFIX_WORDS.has(tokens[tokens.length - 1]!)) {
    tokens.pop();
  }
  return tokens.join(" ");
}

function isUsefulPhrase(value: string): boolean {
  const tokens = value.split(/\s+/).filter(Boolean);
  if (tokens.length && tokens.every((token) => LOW_VALUE_WORDS.has(token))) return false;
  if (tokens.length >= 2) return true;
  return Boolean(tokens.length && ["_", "-", ".", "/"].some((char) => tokens[0]!.includes(char)));
}

function addPhrase(phrases: string[], value: string): void {
  const phrase = normalizePhraseText(value);
  if (isUsefulPhrase(phrase)) phrases.push(phrase);
}

function hasContentToken(value: string): boolean {
  return normalizePhraseText(value)
    .split(/\s+/)
    .filter(Boolean)
    .some((token) => !LOW_VALUE_WORDS.has(token));
}

function topicLabel(value: string): string {
  const tokens = normalizePhraseText(value).split(/\s+/).filter(Boolean);
  while (tokens.length > 1 && GENERIC_TOPIC_SUFFIXES.has(tokens[tokens.length - 1]!)) {
    tokens.pop();
  }
  return tokens.slice(0, 4).join(" ");
}

function sourceLabel(value: string): string {
  const first = normalizePhraseText(value).split(/\s+/).filter(Boolean)[0] ?? "";
  return first ? first.split(/[_./+-]+/)[0]! : "";
}

function splitOnce(value: string, pattern: RegExp): [string, string] | null {
  const index = value.search(pattern);
  if (index === -1) return null;
  const match = pattern.exec(value);
  if (!match) return null;
  return [value.slice(0, index), value.slice(index + match[0].length)];
}

function phraseVariants(text: string, forQuery: boolean): string[] {
  const phrases: string[] = [];
  if (text.includes(":")) {
    const [left, right] = [text.slice(0, text.indexOf(":")), text.slice(text.indexOf(":") + 1)];
    phrases.push(...phraseVariants(left, forQuery));
    phrases.push(...phraseVariants(right, forQuery));
    return phrases;
  }

  let base = normalizePhraseText(text);
  if (!base) return phrases;

  if (forQuery) {
    base = base.replace(QUERY_PREFIX_RE, "").trim();
    base = trimQuerySuffix(base);
  }

  const isPreference = /^(?:users?\s+)?(?:prefer|prefers|preferred|like|likes|want|wants|use|uses|need|needs)\s+/.test(
    base,
  );
  const isDecision = /^(?:we\s+)?decided\s+(?:that\s+)?/.test(base);
  base = stripLeadingContext(base);
  if (!base) return phrases;

  if (base.includes(":")) {
    const index = base.indexOf(":");
    addPhrase(phrases, base.slice(0, index));
    base = base.slice(index + 1).trim() || base.slice(0, index);
  }

  const clauseParts = splitOnce(base, TRAILING_CLAUSE_RE);
  if (clauseParts) {
    addPhrase(phrases, clauseParts[0]);
    if (isDecision) addPhrase(phrases, `${topicLabel(clauseParts[0])} decision`);
    base = clauseParts[0];
  }

  const modalParts = splitOnce(base, MODAL_CLAUSE_RE);
  if (modalParts) {
    addPhrase(phrases, modalParts[0]);
    const requirement = modalParts[1].replace(LEADING_VERB_RE, "").trim();
    addPhrase(phrases, requirement);
    const requirementTopic = topicLabel(requirement);
    const sourceTopic = sourceLabel(modalParts[0]);
    addPhrase(phrases, `${requirementTopic} requirement`);
    if (sourceTopic && requirementTopic) {
      addPhrase(phrases, `${sourceTopic} ${requirementTopic}`);
    }
    base = modalParts[0];
  }

  const separators = base.split(SEPARATOR_RE).filter(Boolean);
  if (separators.length > 1) {
    for (const part of separators) addPhrase(phrases, part);
    const preferenceTopic = topicLabel(separators[separators.length - 1]!);
    if (isPreference && hasContentToken(preferenceTopic)) {
      addPhrase(phrases, `${preferenceTopic} preference`);
    }
  } else {
    addPhrase(phrases, base);
    const preferenceTopic = topicLabel(base);
    if (isPreference && hasContentToken(preferenceTopic)) {
      addPhrase(phrases, `${preferenceTopic} preference`);
    }
  }

  return phrases;
}

function extractPlainPhrases(text: string, forQuery = false): string[] {
  const phrases: string[] = [];
  const withoutTerms = text
    .replace(PATH_RE, " ")
    .replace(QUOTE_RE, " ")
    .replace(BACKTICK_RE, " ");

  for (const match of withoutTerms.matchAll(SENTENCE_RE)) {
    const sentence = match[0].trim();
    if (!sentence) continue;
    phrases.push(...phraseVariants(sentence, forQuery));
    if (phrases.length >= MAX_CUES) break;
  }
  return phrases;
}

export function generateCues(content: string): string[] {
  return normalizeCues([...extractTerms(content), ...extractPlainPhrases(content)]);
}

export function expandQueryTerms(query: string): string[] {
  const base = cleanTerm(query);
  if (!base) return [];
  const explicit = extractTerms(query);
  if (explicit.length) return normalizeCues([base, ...explicit]);
  return normalizeCues([base, ...extractPlainPhrases(query, true)]);
}
