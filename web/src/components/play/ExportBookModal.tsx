"use client";

// QA-001: extracted from app/play/[gameId]/page.tsx. Tiny status modal shown
// after an export-book attempt fails (success opens a download window
// directly, so this only renders the error message).
import { Modal } from "@/components/ui/Modal";

export function ExportBookModal({
  open,
  onClose,
  message,
}: {
  open: boolean;
  onClose: () => void;
  message: string | null;
}) {
  return (
    <Modal open={open} onClose={onClose} title="Export Book">
      <p className="text-sm text-gray-300">{message}</p>
    </Modal>
  );
}
