"use client";

import { Html5Qrcode } from "html5-qrcode";
import { useEffect, useRef, useState } from "react";

const elementId = "walk-up-camera";

// PUBLIC_INTERFACE
/**
 * Reads a QR code live from the kiosk camera and returns the first one it sees.
 * The camera starts only when the operator presses the button, and stops after a scan.
 */
export function WalkUpCameraScanner({
  onScan,
  disabled = false
}: {
  onScan: (payload: string) => void;
  disabled?: boolean;
}) {
  const scannerRef = useRef<Html5Qrcode | null>(null);
  const [active, setActive] = useState(false);
  const [error, setError] = useState("");

  async function stop() {
    const scanner = scannerRef.current;
    scannerRef.current = null;
    setActive(false);
    if (!scanner) return;
    try {
      await scanner.stop();
    } catch {
      // The camera may already be stopped.
    }
    try {
      scanner.clear();
    } catch {
      // Nothing to clear.
    }
  }

  async function start() {
    if (scannerRef.current || disabled) return;
    setError("");
    setActive(true);
    // Give React a moment to render the video area before the library attaches to it.
    await new Promise((resolve) => setTimeout(resolve, 50));
    const scanner = new Html5Qrcode(elementId, false);
    scannerRef.current = scanner;
    try {
      await scanner.start(
        { facingMode: "environment" },
        { fps: 10, qrbox: { width: 240, height: 240 } },
        (payload) => {
          void stop();
          onScan(payload);
        },
        () => undefined
      );
    } catch {
      scannerRef.current = null;
      setActive(false);
      setError(
        "The camera could not be started. Allow camera access for this page (it needs https or localhost), or use the image upload or type the reference instead."
      );
    }
  }

  useEffect(() => {
    return () => {
      void stop();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="space-y-2">
      {active ? (
        <button
          className="rounded-lg border px-3 py-2 text-sm font-semibold text-slate-800"
          onClick={() => void stop()}
          type="button"
        >
          Stop camera
        </button>
      ) : (
        <button
          className="rounded-lg bg-emerald-700 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50"
          disabled={disabled}
          onClick={() => void start()}
          type="button"
        >
          Scan with camera
        </button>
      )}
      <div
        className={active ? "mt-2 max-w-sm overflow-hidden rounded-lg border" : "hidden"}
        id={elementId}
      />
      {error ? (
        <p role="alert" className="text-sm text-red-700">
          {error}
        </p>
      ) : null}
    </div>
  );
}
