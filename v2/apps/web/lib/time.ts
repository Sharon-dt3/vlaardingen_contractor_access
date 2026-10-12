// One clock for the whole app: the site's own time zone. Every site is in the Netherlands or
// Belgium, which share Central European time (daylight saving included).
export const SITE_TIME_ZONE = process.env.NEXT_PUBLIC_SITE_TIME_ZONE || "Europe/Amsterdam";

function offsetMinutes(zone: string, atUtcMs: number): number {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-US", {
      timeZone: zone,
      hourCycle: "h23",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit"
    })
      .formatToParts(new Date(atUtcMs))
      .map((part) => [part.type, part.value])
  );
  const asUtc = Date.UTC(
    Number(parts.year),
    Number(parts.month) - 1,
    Number(parts.day),
    Number(parts.hour),
    Number(parts.minute),
    Number(parts.second)
  );
  return (asUtc - atUtcMs) / 60000;
}

/** An instant as "YYYY-MM-DDTHH:mm" on the site's clock, the format a datetime-local input uses. */
export function isoToSiteInput(iso: string): string {
  const ms = new Date(iso).getTime();
  return new Date(ms + offsetMinutes(SITE_TIME_ZONE, ms) * 60000).toISOString().slice(0, 16);
}

/** What a datetime-local input says, read as the site's clock, as an exact instant (ISO string). */
export function siteInputToIso(value: string): string {
  const [datePart, timePart] = value.split("T");
  const [year, month, day] = datePart.split("-").map(Number);
  const [hour, minute] = timePart.split(":").map(Number);
  const guess = Date.UTC(year, month - 1, day, hour, minute);
  let ms = guess - offsetMinutes(SITE_TIME_ZONE, guess) * 60000;
  ms = guess - offsetMinutes(SITE_TIME_ZONE, ms) * 60000; // settle across a daylight saving change
  return new Date(ms).toISOString();
}

/** The same moment on the viewer's own clock, or "" when it is the same clock as the site's. */
export function yourClockHint(iso: string): string {
  const ms = new Date(iso).getTime();
  const browserOffset = -new Date(ms).getTimezoneOffset();
  if (browserOffset === offsetMinutes(SITE_TIME_ZONE, ms)) return "";
  return new Intl.DateTimeFormat(undefined, {
    day: "numeric",
    month: "short",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short"
  }).format(new Date(ms));
}
