# Channel Onboarding

This system should configure channels in this order:

1. Discord for shared project coordination.
2. Telegram for owner-private approvals and alerts.
3. WhatsApp only if notify-only coverage is still useful.

## Discord

Use Discord for friends and joint apps.

Required from the owner:

- `DISCORD_BOT_TOKEN`
- Discord application/client id
- shared development server/guild id
- allowed category/channel ids
- owner Discord user id, if Discord should be an owner route

Secure defaults:

- `dmPolicy: "pairing"`
- `groupPolicy: "allowlist"`
- allowed guilds only
- require bot mention in project channels
- no owner-only approvals in shared channels

Draft config shape:

```json5
{
  channels: {
    discord: {
      enabled: true,
      token: { source: "env", provider: "default", id: "DISCORD_BOT_TOKEN" },
      applicationId: "DISCORD_APPLICATION_ID",
      dmPolicy: "pairing",
      groupPolicy: "allowlist",
      guilds: {
        "DISCORD_GUILD_ID": {
          requireMention: true,
          ignoreOtherMentions: true,
          channels: {
            "DISCORD_CHANNEL_ID": {
              allow: true,
              requireMention: true,
            },
          },
        },
      },
      execApprovals: {
        enabled: false,
      },
    },
  },
}
```

## Telegram

Use Telegram for the owner's private operator route.

Required from the owner:

- `TELEGRAM_BOT_TOKEN`
- owner Telegram user id

Secure defaults:

- owner DM only
- owner approvals and alerts allowed
- group behavior remains allowlist/mention-gated

After the owner id is known, set:

```bash
openclaw config set commands.ownerAllowFrom '["telegram:OWNER_TELEGRAM_USER_ID"]'
```

## WhatsApp

Leave WhatsApp unconfigured until needed.

Default policy:

- notify-only
- no approvals
- no source of truth
- no project deconfliction

## Collaboration Invariant

For joint development:

`one task = one GitHub issue + one DontPanic plan + one branch + one Discord thread`

Dashboards should aggregate from GitHub/DontPanic artifacts first, then link to the
Discord thread for discussion context.
