// Only relevant for the morning commute -- skip firing outside this window
// entirely, rather than letting check.yml run and no-op every 10 minutes
// around the clock. Uses the Europe/Kyiv timezone (not a hardcoded UTC
// offset) so this keeps working correctly across the DST transition, and
// checks the weekday the same way so weekends are skipped too.
const ACTIVE_HOURS_START = 7; // inclusive
const ACTIVE_HOURS_END = 12; // exclusive
const WEEKEND_DAYS = new Set(["Sat", "Sun"]);

function isWithinActiveWindow() {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Europe/Kyiv",
    hour: "2-digit",
    hour12: false,
    weekday: "short",
  }).formatToParts(new Date());

  const kyivHour = Number(parts.find((p) => p.type === "hour").value);
  const kyivWeekday = parts.find((p) => p.type === "weekday").value;

  if (WEEKEND_DAYS.has(kyivWeekday)) {
    return false;
  }
  return kyivHour >= ACTIVE_HOURS_START && kyivHour < ACTIVE_HOURS_END;
}

export default {
  async scheduled(event, env, ctx) {
    if (!isWithinActiveWindow()) {
      return;
    }

    ctx.waitUntil(
      fetch(
        `https://api.github.com/repos/${env.GITHUB_OWNER}/${env.GITHUB_REPO}/actions/workflows/check.yml/dispatches`,
        {
          method: "POST",
          headers: {
            Authorization: `Bearer ${env.GH_TOKEN}`,
            Accept: "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "uz-prymisky-bot-cron",
          },
          body: JSON.stringify({ ref: "main" }),
        }
      ).then(async (response) => {
        console.log("GitHub dispatch status:", response.status, await response.text());
      })
    );
  },
};
