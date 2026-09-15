export default {
  async scheduled(event, env, ctx) {
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
      )
    );
  },
};
