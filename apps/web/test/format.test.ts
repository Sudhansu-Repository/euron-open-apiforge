import { describe, expect, it } from "vitest";

import { emailName, formatBytes, formatCompact, formatDuration, formatNumber, formatRelative, initials, plural, shortSha } from "@/lib/format";

describe("formatBytes", () => {
  it("uses binary multiples and drops a trailing .0", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(1023)).toBe("1023 B");
    expect(formatBytes(2048)).toBe("2 KB");
    expect(formatBytes(22_309)).toBe("21.8 KB");
    expect(formatBytes(5 * 1024 * 1024)).toBe("5 MB");
    expect(formatBytes(1.5 * 1024 ** 3)).toBe("1.5 GB");
  });
  it("never renders a missing size as zero", () => {
    expect(formatBytes(null)).toBe("n/a");
    expect(formatBytes(undefined)).toBe("n/a");
    expect(formatBytes(-1)).toBe("n/a");
  });
});

describe("formatDuration", () => {
  it("picks a unit that reads well", () => {
    expect(formatDuration(76)).toBe("76 ms");
    expect(formatDuration(999.6)).toBe("1000 ms");
    expect(formatDuration(1234)).toBe("1.23 s");
    expect(formatDuration(12_400)).toBe("12.4 s");
    expect(formatDuration(125_000)).toBe("2m 05s");
  });
  it("says n/a for a generation still running", () => {
    expect(formatDuration(null)).toBe("n/a");
  });
});

describe("numbers and names", () => {
  it("formats counts and plurals", () => {
    expect(formatNumber(14923)).toBe("14,923");
    expect(formatCompact(13_900_000)).toBe("13.9M");
    expect(plural(1, "operation")).toBe("1 operation");
    expect(plural(4, "operation")).toBe("4 operations");
    expect(plural(0, "spec version")).toBe("0 spec versions");
  });
  it("shortens digests, emails and names", () => {
    expect(shortSha("3abc32a95e8777f0f609091762daa14e")).toBe("3abc32a95e87");
    expect(shortSha(null)).toBe("n/a");
    expect(emailName("admin@apiforge.local")).toBe("admin");
    expect(emailName(null)).toBe("System");
    expect(initials("Priya Raman")).toBe("PR");
  });
  it("describes times relative to now", () => {
    const now = new Date("2026-10-28T12:00:00Z");
    expect(formatRelative("2026-10-28T11:59:40Z", now)).toBe("just now");
    expect(formatRelative("2026-10-28T11:30:00Z", now)).toBe("30m ago");
    expect(formatRelative("2026-10-26T12:00:00Z", now)).toBe("2d ago");
    expect(formatRelative(null, now)).toBe("Never");
  });
});
