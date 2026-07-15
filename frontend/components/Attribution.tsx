// MANDATORY under the Indian Kanoon API licence: whenever IK results are shown
// to a user (direct display) the "Powered by Indian Kanoon" logo must appear on
// top of the results, on both desktop and mobile; and for integrated/RAG use it
// must appear in a prominent place (footer/About).
//
// The SVGs in /public reproduce the official mark (orange rings + blue "i" +
// "kanoon"). For strict brand compliance, replace them with the exact asset
// from the IKanoon API Terms page — do NOT alter, disproportionately resize, or
// partially cover it, and never imply IKanoon endorsement of Nyaya.

export function Attribution({ compact = false }: { compact?: boolean }) {
  const h = compact ? "h-6" : "h-9";
  return (
    <a
      href="https://www.indiankanoon.org/"
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center"
      aria-label="Powered by Indian Kanoon"
      title="Powered by Indian Kanoon"
    >
      {/* Desktop / larger screens: full wordmark */}
      <img
        src="/powered-by-ikanoon.svg"
        alt="Powered by Indian Kanoon"
        className={`hidden sm:block ${h} w-auto`}
      />
      {/* Mobile: stacked icon */}
      <img
        src="/powered-by-ikanoon-mobile.svg"
        alt="Powered by Indian Kanoon"
        className={`block sm:hidden ${compact ? "h-8" : "h-11"} w-auto`}
      />
    </a>
  );
}
