import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiGet, apiPost, apiPostForm } from "@/lib/api";
import { useCharacterActions } from "./useCharacterActions";

vi.mock("@/lib/api", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPostForm: vi.fn(),
  apiDelete: vi.fn(),
  apiPut: vi.fn(),
}));

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiGet).mockResolvedValue({ characters: [] });
});

describe("character creation", () => {
  it("sends the reference to the multipart endpoint in the initial request", async () => {
    const { result } = renderHook(() => useCharacterActions());
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    const reference = new File(["image"], "ref.png", { type: "image/png" });
    await act(async () => {
      await result.current.createCharacter({
        concept: " a scholar ", name: " Alyx ", referenceImage: reference,
      });
    });
    expect(apiPostForm).toHaveBeenCalledTimes(1);
    const [url, form] = vi.mocked(apiPostForm).mock.calls[0];
    expect(url).toBe("/api/characters/create-with-reference");
    expect(form.get("concept")).toBe("a scholar");
    expect(form.get("name")).toBe("Alyx");
    expect(form.get("reference_image")).toBe(reference);
    expect(apiPost).not.toHaveBeenCalled();
  });

  it("keeps JSON creation for characters without a reference", async () => {
    const { result } = renderHook(() => useCharacterActions());
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    await act(async () => {
      await result.current.createCharacter({
        concept: " a scholar ", name: "", referenceImage: null,
      });
    });
    expect(apiPost).toHaveBeenCalledExactlyOnceWith("/api/characters/create", {
      concept: "a scholar",
    });
    expect(apiPostForm).not.toHaveBeenCalled();
  });
});
