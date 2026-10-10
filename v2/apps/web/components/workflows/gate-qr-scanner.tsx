"use client";

import { useRef, useState } from "react";
import { Html5Qrcode } from "html5-qrcode";

type GateQrScannerProps = {
  onScan: (payload: string) => void;
  onError: (message: string) => void;
  disabled?: boolean;
  /** Distinguishes element ids when two scanners share one page. */
  idSuffix?: string;
};

const scannerElementBaseId = "gate-qr-image";
const maxQrImageBytes = 5 * 1024 * 1024;

// PUBLIC_INTERFACE
/**
 * Decodes an issued access QR from an uploaded image and returns its payload.
 * The decoded credential must still be validated by the Gate API.
 */
export function GateQrScanner({
  onScan,
  onError,
  disabled = false,
  idSuffix = ""
}: GateQrScannerProps) {
  const scannerElementId = `${scannerElementBaseId}${idSuffix}`;
  const fileInputId = `gate-qr-file${idSuffix}`;
  const [isScanning, setIsScanning] = useState(false);
  const [scanError, setScanError] = useState<string | null>(null);
  const scanningRef = useRef(false);

  async function scanImage(file: File | undefined) {
    if (!file || scanningRef.current) {
      return;
    }

    setScanError(null);
    if (!file.type.startsWith("image/") || file.size === 0 || file.size > maxQrImageBytes) {
      const message = "Choose a non-empty QR image of 5 MiB or less.";
      setScanError(message);
      onError(message);
      return;
    }

    scanningRef.current = true;
    setIsScanning(true);
    const scanner = new Html5Qrcode(scannerElementId, false);
    try {
      // scanFile reads the selected image; it does not request camera access.
      const payload = await scanner.scanFile(file, false);
      onScan(payload);
    } catch {
      const message = "No readable QR code was found in this image. Choose a clear issued QR image.";
      setScanError(message);
      onError(message);
    } finally {
      try {
        scanner.clear();
      } catch {
        // Decoding failures may leave no scanner resources to clear.
      }
      scanningRef.current = false;
      setIsScanning(false);
    }
  }

  return (
    <div className="space-y-2">
      <label className="block text-xs font-semibold uppercase tracking-wide text-slate-600" htmlFor={fileInputId}>
        Issued QR image
      </label>
      <input
        accept="image/*"
        className="block w-full text-sm text-slate-700"
        disabled={disabled || isScanning}
        id={fileInputId}
        onChange={(event) => {
          const file = event.target.files?.[0];
          // Allow retrying the same image after a decoding error.
          event.target.value = "";
          void scanImage(file);
        }}
        type="file"
      />
      <p className="text-xs text-muted-foreground">
        Upload a clear image of the issued QR code (maximum 5 MiB).
        {isScanning ? " Scanning image…" : ""}
      </p>
      {scanError ? (
        <p aria-live="assertive" className="text-sm text-red-700">
          {scanError}
        </p>
      ) : null}
      <div className="hidden" id={scannerElementId} />
    </div>
  );
}
