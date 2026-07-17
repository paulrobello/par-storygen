// QA-003: smoke test for the EndingsModal (extracted in QA-001). Renders a
// list of ending node ids with a narration preview; clicking a row calls
// onJumpTo. Pins: empty-state copy, populated rendering (id prefix + preview
// truncated from the node narration), the open=false no-render gate, the
// onJumpTo callback, and the Modal-level Escape-to-close onClose wiring.
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { EndingsModal } from "./EndingsModal";
import { NODE_DEFAULTS, type StoryNode } from "@/lib/api";

function makeNode(id: string, narration: string): StoryNode {
  return {
    ...NODE_DEFAULTS,
    id,
    narration,
    created_at: "2026-01-01T00:00:00Z",
  };
}

describe("EndingsModal", () => {
  it("renders the empty-state message when no endings have been reached", () => {
    render(
      <EndingsModal
        open
        onClose={vi.fn()}
        endingsList={[]}
        nodes={{}}
        onJumpTo={vi.fn()}
      />,
    );
    expect(screen.getByText(/no endings reached yet/i)).toBeInTheDocument();
  });

  it("renders each ending id prefix and a narration preview", () => {
    const nodes: Record<string, StoryNode> = {
      "ending-1234": makeNode("ending-1234", "You chose the door and fell."),
    };
    render(
      <EndingsModal
        open
        onClose={vi.fn()}
        endingsList={["ending-1234"]}
        nodes={nodes}
        onJumpTo={vi.fn()}
      />,
    );

    // id prefix (first 8 chars) and narration preview are both shown.
    expect(screen.getByText("ending-1")).toBeInTheDocument();
    expect(
      screen.getByText(/you chose the door and fell/i),
    ).toBeInTheDocument();
  });

  it("renders 'Unknown node' when an ending id has no matching node", () => {
    render(
      <EndingsModal
        open
        onClose={vi.fn()}
        endingsList={["ghost"]}
        nodes={{}}
        onJumpTo={vi.fn()}
      />,
    );
    expect(screen.getByText(/unknown node/i)).toBeInTheDocument();
  });

  it("calls onJumpTo with the node id when its row is clicked", () => {
    const onJumpTo = vi.fn();
    const nodes: Record<string, StoryNode> = {
      "ending-1234": makeNode("ending-1234", "narration"),
    };
    render(
      <EndingsModal
        open
        onClose={vi.fn()}
        endingsList={["ending-1234"]}
        nodes={nodes}
        onJumpTo={onJumpTo}
      />,
    );

    fireEvent.click(screen.getByText("ending-1"));

    expect(onJumpTo).toHaveBeenCalledWith("ending-1234");
    expect(onJumpTo).toHaveBeenCalledTimes(1);
  });

  it("renders nothing when open is false", () => {
    const { container } = render(
      <EndingsModal
        open={false}
        onClose={vi.fn()}
        endingsList={["x"]}
        nodes={{}}
        onJumpTo={vi.fn()}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("calls onClose when Escape is pressed (Modal-level)", () => {
    const onClose = vi.fn();
    render(
      <EndingsModal
        open
        onClose={onClose}
        endingsList={[]}
        nodes={{}}
        onJumpTo={vi.fn()}
      />,
    );

    fireEvent.keyDown(document, { key: "Escape" });

    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
