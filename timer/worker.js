// Planet Briefing — backup timer (Cloudflare Worker with a Cron Trigger).
//
// GitHub's own schedule is unreliable for new projects, so this Worker presses
// GitHub's "Run workflow" button at :07 and :37 past every hour.
//
// Set up in Cloudflare (Workers & Pages):
//   - Paste this file as the Worker's code.
//   - Settings → Triggers → Cron Triggers: 7,37 * * * *
//   - Settings → Variables and Secrets → add a *Secret* named GITHUB_TOKEN
//     holding a fine-grained GitHub token with access to only the
//     planet-briefing repository and the permission "Actions: Read and write".
//
// The token expires after a year: make a new one and replace the secret.

const REPO = "hadssm52/planet-briefing";
const WORKFLOW = "daily.yml";

async function runWorkflow(env) {
  const response = await fetch(
    `https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.GITHUB_TOKEN}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "planet-briefing-timer",
      },
      body: JSON.stringify({ ref: "main" }),
    },
  );
  if (!response.ok) {
    // Shows up in the Worker's logs in Cloudflare.
    throw new Error(`GitHub refused to start the update (${response.status}): ${await response.text()}`);
  }
}

export default {
  // Called by the Cron Trigger.
  async scheduled(event, env, ctx) {
    ctx.waitUntil(runWorkflow(env));
  },

  // Visiting the Worker's address just says what it is; it never starts a run,
  // so strangers can't trigger updates.
  async fetch() {
    return new Response("Planet Briefing timer: starts the site update every 30 minutes.\n", {
      headers: { "Content-Type": "text/plain" },
    });
  },
};
