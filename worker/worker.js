export default {
  async scheduled(event, env, ctx) {
    const githubRequest = fetch(
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
      console.log("GitHub status:", response.status);
      console.log("GitHub response:", await response.text());
    }).catch((error) => {
      console.log("ERROR:", error.message);
    });

    ctx.waitUntil(githubRequest);
  },
};
