const languages = new Intl.DisplayNames(["en"], { type: "language" });
const scripts = new Intl.DisplayNames(["en"], { type: "script" });

/** ISO 639-1 (or 639-3) code to an English name; the code itself when the runtime does not know it. */
export function languageName(code: string | null | undefined) {
  if (!code) return "Not recorded";
  try {
    return languages.of(code) ?? code;
  } catch {
    return code;
  }
}

/** ISO 15924 code to an English name ("Taml" becomes "Tamil"). */
export function scriptName(code: string | null | undefined) {
  if (!code) return "Not recorded";
  try {
    return scripts.of(code) ?? code;
  } catch {
    return code;
  }
}

/** Categories as they are written in claims, as people read them. */
export function categoryLabel(category: string) {
  const text = category.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

/** `2027-10-29` read as a calendar day, with no time zone shift. */
export function dayLabel(iso: string) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Intl.DateTimeFormat("en", { day: "numeric", month: "short", year: "numeric" }).format(new Date(y, m - 1, d));
}

export function dayOfMonth(iso: string) {
  return Number(iso.split("-")[2]);
}

/** Native-script spelling for the languages the product sets in type, so the right Noto face applies. */
export function langAttr(code: string | null | undefined) {
  return code ?? undefined;
}
