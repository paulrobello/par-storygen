// QA-003: smoke test for the RecapModal (extracted in QA-001). Renders the
// "Previously on..." recap text via react-markdown, plus Read Aloud (TTS) and
// Close buttons. Pins: title, markdown body render, Read Aloud disabled state
// while ttsLoading or when recapText is empty, the onReadAloud + onClose
// callbacks, and the open=false no-render gate.
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { RecapModal } from "./RecapModal";

describe("RecapModal", () => {
  it("renders the title and the recap text as rendered markdown", () => {
    render(
      <RecapModal
        open
        onClose={vi.fn()}
        recapText="**The hero fell.**"
        onReadAloud={vi.fn().mockResolvedValue(undefined)}
        ttsLoading={false}
      />,
    );

    expect(screen.getByText(/previously on/i)).toBeInTheDocument();
    // react-markdown renders **bold** as <strong>.
    expect(screen.getByText("The hero fell.")).toBeInTheDocument();
  });

  it("enables Read Aloud when recap text is present and TTS is not loading", () => {
    render(
      <RecapModal
        open
        onClose={vi.fn()}
        recapText="recap"
        onReadAloud={vi.fn().mockResolvedValue(undefined)}
        ttsLoading={false}
      />,
    );

    expect(screen.getByRole("button", { name: /read aloud/i })).toBeEnabled();
  });

  it("disables Read Aloud and replaces its label with a spinner while TTS is loading", () => {
    render(
      <RecapModal
        open
        onClose={vi.fn()}
        recapText="recap"
        onReadAloud={vi.fn().mockResolvedValue(undefined)}
        ttsLoading
      />,
    );

    // While loading the "Read Aloud" label is swapped out for a pulsing
    // spinner, leaving the button without an accessible name — so query the
    // disabled control directly rather than by role+name.
    expect(screen.queryByText("Read Aloud")).toBeNull();
    const disabled = screen
      .getAllByRole("button")
      .filter((b) => b.hasAttribute("disabled"));
    expect(disabled).toHaveLength(1);
    expect(disabled[0]).toBeDisabled();
  });

  it("disables Read Aloud when there is no recap text", () => {
    render(
      <RecapModal
        open
        onClose={vi.fn()}
        recapText=""
        onReadAloud={vi.fn().mockResolvedValue(undefined)}
        ttsLoading={false}
      />,
    );

    expect(screen.getByRole("button", { name: /read aloud/i })).toBeDisabled();
  });

  it("calls onReadAloud when Read Aloud is clicked", () => {
    const onReadAloud = vi.fn().mockResolvedValue(undefined);
    render(
      <RecapModal
        open
        onClose={vi.fn()}
        recapText="recap"
        onReadAloud={onReadAloud}
        ttsLoading={false}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /read aloud/i }));

    expect(onReadAloud).toHaveBeenCalledTimes(1);
  });

  it("calls onClose when the Close button is clicked", () => {
    const onClose = vi.fn();
    render(
      <RecapModal
        open
        onClose={onClose}
        recapText="recap"
        onReadAloud={vi.fn().mockResolvedValue(undefined)}
        ttsLoading={false}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /^close$/i }));

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("renders nothing when open is false", () => {
    const { container } = render(
      <RecapModal
        open={false}
        onClose={vi.fn()}
        recapText="recap"
        onReadAloud={vi.fn().mockResolvedValue(undefined)}
        ttsLoading={false}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
