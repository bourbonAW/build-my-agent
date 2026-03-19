"""Todo management system."""

from dataclasses import dataclass, field


@dataclass
class TodoItem:
    """A single todo item."""

    content: str
    status: str = "pending"  # pending, in_progress, completed
    active_form: str = field(default="")

    def to_dict(self) -> dict:
        """Convert to dictionary for LLM communication."""
        return {
            "content": self.content,
            "status": self.status,
            "activeForm": self.active_form,
        }


class TodoManager:
    """Manages todo items for the agent."""

    MAX_TODOS = 20
    VALID_STATUSES = {"pending", "in_progress", "completed"}

    def __init__(self):
        """Initialize empty todo list."""
        self.items: list[TodoItem] = []

    def update(self, items: list[dict]) -> str:
        """Update todo list from LLM input.

        Args:
            items: List of todo dictionaries with content, status, activeForm

        Returns:
            Rendered todo list

        Raises:
            ValueError: If validation fails
        """
        validated: list[TodoItem] = []
        in_progress_count = 0

        for i, item in enumerate(items):
            content = str(item.get("content", "")).strip()
            status = str(item.get("status", "pending")).lower()
            active_form = str(item.get("activeForm", "")).strip()

            if not content:
                raise ValueError(f"Item {i}: content required")

            if status not in self.VALID_STATUSES:
                raise ValueError(f"Item {i}: invalid status '{status}'")

            if not active_form:
                raise ValueError(f"Item {i}: activeForm required")

            if status == "in_progress":
                in_progress_count += 1

            validated.append(
                TodoItem(
                    content=content,
                    status=status,
                    active_form=active_form,
                )
            )

        if len(validated) > self.MAX_TODOS:
            raise ValueError(f"Max {self.MAX_TODOS} todos")

        if in_progress_count > 1:
            raise ValueError("Only one in_progress allowed")

        self.items = validated
        return self.render()

    def render(self) -> str:
        """Render todo list as formatted string."""
        if not self.items:
            return "No todos."

        lines = []
        for item in self.items:
            status_mark = {
                "completed": "x",
                "in_progress": ">",
                "pending": " ",
            }.get(item.status, "?")

            suffix = f" <- {item.active_form}" if item.status == "in_progress" else ""
            lines.append(f"[{status_mark}] {item.content}{suffix}")

        completed = sum(1 for t in self.items if t.status == "completed")
        lines.append(f"\n({completed}/{len(self.items)} completed)")

        return "\n".join(lines)

    def has_open_items(self) -> bool:
        """Check if there are any non-completed items."""
        return any(item.status != "completed" for item in self.items)

    def to_list(self) -> list[dict]:
        """Export todos as list of dictionaries."""
        return [item.to_dict() for item in self.items]
