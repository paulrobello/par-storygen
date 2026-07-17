// QA-003: smoke test for the RelationshipsModal (extracted in QA-001 from the
// play page). Pure presentational component — the page passes open/onClose +
// the relationships/characters data. These tests pin the empty-state copy, the
// populated rendering (both names + type + context), the unknown-character id
// fallback, the open=false no-render gate, and the Modal-level Escape-to-close
// onClose wiring. No async, no store dependency.
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { RelationshipsModal } from "./RelationshipsModal";
import type { Character, Relationship } from "@/lib/api";

function makeChar(id: string, name: string): Character {
  return {
    id,
    name,
    backstory: "",
    backstory_summary: null,
    personality: "",
    physical_description: "",
    portrait_path: null,
    portrait_prompt: null,
    introduced_at_node_id: "root",
    outfits: [],
    current_outfit_id: null,
    reference_image_path: null,
  };
}

const characters: Character[] = [makeChar("c1", "Alyx"), makeChar("c2", "Bram")];

describe("RelationshipsModal", () => {
  it("renders the empty-state message when there are no relationships", () => {
    render(
      <RelationshipsModal
        open
        onClose={vi.fn()}
        relationships={[]}
        characters={[]}
      />,
    );
    expect(
      screen.getByText(/no relationships discovered yet/i),
    ).toBeInTheDocument();
  });

  it("renders each relationship with both character names, the type badge, and context", () => {
    const rels: Relationship[] = [
      {
        char_a_id: "c1",
        char_b_id: "c2",
        type: "ally",
        strength: 3,
        context: "met in chapter one",
        updated_at_node_id: "root",
      },
    ];
    render(
      <RelationshipsModal
        open
        onClose={vi.fn()}
        relationships={rels}
        characters={characters}
      />,
    );

    expect(screen.getByText("Alyx")).toBeInTheDocument();
    expect(screen.getByText("Bram")).toBeInTheDocument();
    expect(screen.getByText("ally")).toBeInTheDocument();
    expect(screen.getByText("met in chapter one")).toBeInTheDocument();
  });

  it("falls back to the 8-char id prefix when a character is not in the roster", () => {
    const rels: Relationship[] = [
      {
        char_a_id: "unknown-id-xyz",
        char_b_id: "c2",
        type: "rival",
        strength: 1,
        context: "",
        updated_at_node_id: "root",
      },
    ];
    render(
      <RelationshipsModal
        open
        onClose={vi.fn()}
        relationships={rels}
        characters={characters}
      />,
    );

    // The modal slices an unknown id to its first 8 chars.
    expect(screen.getByText("unknown-")).toBeInTheDocument();
    expect(screen.getByText("Bram")).toBeInTheDocument();
  });

  it("renders nothing when open is false", () => {
    const { container } = render(
      <RelationshipsModal
        open={false}
        onClose={vi.fn()}
        relationships={[]}
        characters={[]}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("calls onClose when Escape is pressed (Modal-level)", () => {
    const onClose = vi.fn();
    render(
      <RelationshipsModal
        open
        onClose={onClose}
        relationships={[]}
        characters={[]}
      />,
    );

    fireEvent.keyDown(document, { key: "Escape" });

    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
