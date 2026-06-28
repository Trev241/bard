# SPEC

## Purpose

This document describes what Bard is expected to be, what features it should support, and what improvement goals should guide future development.

This is a specification document only. It does not require implementation by itself.

## Product Summary

Bard is a self-hosted Discord bot for personal music playback.

It should let users request music in Discord, stream that music into a Discord voice channel, manage a shared queue, and control playback through both Discord commands and a local web dashboard.

Bard should stay focused on being a reliable personal Discord music bot rather than becoming a public multi-server service.

## Primary Users

The primary users are:

- The repository owner or host.
- Members of the owner's Discord server.
- Users in a voice channel where Bard is present.

The owner or trusted admins may also use maintenance commands.

## Core Goals

Bard should:

1. Join a Discord voice channel when requested or when appropriate.
2. Search YouTube for requested music.
3. Stream audio through Discord voice.
4. Maintain a predictable playback queue.
5. Expose playback controls through Discord commands.
6. Expose playback controls through a local web dashboard.
7. Remain easy to run in a small self-hosted environment.

## Non-Goals

Bard does not currently need to:

- Support many guilds at the same time.
- Operate as a public hosted service.
- Provide user accounts for the dashboard.
- Replace Discord as the primary interaction surface.
- Support every music platform.
- Add broad unrelated bot features that distract from music playback.
- Build analytical listening-history views or music statistics.

## Functional Requirements

### Discord Startup

Bard must load its Discord token from environment configuration.

Bard must start the Discord client and register the enabled cogs.

Bard must use the `?` command prefix unless a future migration intentionally changes this.

### Voice Connection

Bard must be able to join the voice channel of the requesting user.

Bard must be able to disconnect from the current voice channel.

Bard should avoid joining multiple voice channels at the same time under the current single-session design.

Bard should handle connection-in-progress and disconnection-in-progress states clearly.

### Music Search

Bard must accept a user query or URL.

Bard must search YouTube through `yt-dlp`.

Bard must support both individual video results and playlist results.

Bard should use a shared, centralized `yt-dlp` configuration so all features search and extract music consistently.

### Queue Management

Bard must maintain an ordered queue of songs.

Bard must support:

- Adding one song.
- Adding multiple playlist entries.
- Showing the queue.
- Removing a queued song by index.
- Skipping the current song.
- Skipping multiple songs when requested.
- Looping the current song.
- Looping the queue.

Queue behavior should be deterministic and covered by tests before major changes are made.

### Playback

Bard must stream playable audio into Discord voice using FFmpeg.

Bard must support pause and resume.

Bard must show the current song, requester, duration, thumbnail, and source link when available.

Bard should automatically recover or report clearly when YouTube extraction or FFmpeg playback fails.

### Autoplay

When the queue is exhausted, Bard may add a random song from a configured YouTube playlist.

Autoplay should be configurable.

Autoplay songs should be distinguishable from user-requested songs.

When a user requests a song while autoplay is active, the user-requested song should take priority.

### Web Dashboard

Bard must expose a local dashboard, normally on port `5000`.

The dashboard must show:

- Current track title.
- Current track thumbnail.
- Requester display name.
- Upcoming queue.
- Basic playback state.

The dashboard must allow:

- Submitting a track request.
- Pausing or resuming playback.
- Skipping the current track.
- Toggling loop state.

Dashboard state must update from playback events through Socket.IO.

Dashboard actions must be routed back into the same playback logic used by Discord commands.

### Discord Utilities

Bard may provide convenience utilities, including:

- Repeated pinging until a user responds.
- Automatic pinging after repeated mentions.
- Sticker responses from local files.
- Timezone conversion based on role names.
- Cookie-file updates through trusted Discord interactions.
- Logs, restart, and shutdown commands.
- User issue reports through Discord UI forms that create GitHub issues.

Sensitive utilities must be limited to trusted users or admins.

Issue reporting may be available to normal users, but it must not expose secrets. It should include Discord context and user-provided reproduction details.

### Logging And Debugging

Bard must write runtime logs to a bounded rotating log file.

Logs should include enough context to debug Discord, playback, dashboard, webhook, and watcher failures.

Log output should redact configured secrets before writing or displaying messages.

Trusted Discord users must be able to request a bounded recent log snippet without downloading the full file.

Trusted Discord users may request the current full log file when needed.

The dashboard must expose a recent-log view for local debugging.

### Yordle

Bard may include the Yordle game.

Yordle should:

- Fetch League of Legends champion names.
- Choose one champion name as the target.
- Accept matching-length champion-name guesses.
- Render visual feedback as an image.
- End the game when the correct champion is guessed.

Yordle failures caused by unavailable external data should not prevent the main bot from running.

### Voice Assistant

Bard contains an experimental voice assistant module.

The project should explicitly decide whether this module is:

- Active.
- Experimental but maintained.
- Archived.
- Removed.

If active, it should be guarded by configuration and should not interfere with normal music playback when unavailable.

The maintained direction is wake-word activation, one-shot transcription, deterministic parsing for common music controls, and optional LLM fallback parsing for ambiguous language. LLM parsing must remain optional so basic voice controls can work without internet-hosted inference.

## Configuration Requirements

Bard should use centralized configuration for:

- Discord token.
- Dashboard host and port.
- Public URL.
- Webhook secret.
- Autoplay playlist URL.
- Cookie file path.
- Log path.
- Restart signal paths.
- Bot owner or admin IDs.
- Feature flags for optional modules.
- Whether the watcher refreshes `yt-dlp` before restart.
- Log rotation size, backup count, and default snippet length.
- GitHub repository, issue labels, and token for issue-report creation.

Secrets must not be committed.

Runtime data such as logs, cookies, generated dumps, and restart flags should be treated as local runtime state.

## Security Requirements

The following actions should require owner or admin permission:

- Shutdown.
- Restart.
- Log access.
- GitHub issue-report submission should validate configuration and avoid exposing tokens.
- Cookie updates.
- Mass pinging.
- Any future command that reads secrets, writes runtime files, or affects deployment.

Webhook requests must verify their signatures before writing restart or commit state.

Dashboard controls are currently local-first. If the dashboard is exposed publicly, authentication or network restrictions should be added first.

## Reliability Requirements

Bard should avoid silent failures.

Errors should be logged with enough context to debug:

- Discord API failures.
- YouTube extraction failures.
- FFmpeg playback failures.
- Dashboard rendering failures.
- Webhook verification failures.
- Restart/watchdog failures.

Bare `except` blocks should be replaced with specific exception handling or logged fallback behavior.

## Maintainability Requirements

Future changes should keep the existing user-facing command behavior stable unless a migration is intentional.

Music playback logic should remain testable without needing a live Discord connection.

Discord command handling, web dashboard handling, and core queue/playback behavior should be separated where practical.

Shared constants and paths should not be scattered across unrelated modules.

Generated files and runtime state should not be mixed with source files where avoidable.

## Test Requirements

The highest-priority tests should cover `PlaybackManager` behavior:

- Adding songs.
- Adding autoplay songs.
- Empty queue behavior.
- Skipping one song.
- Skipping multiple songs.
- Removing queued songs.
- Removing the current song.
- Looping one track.
- Looping the queue.
- Suspending and resuming playback flow.

Additional tests should cover:

- Signature verification for webhooks.
- Configuration loading defaults.
- Permission checks for sensitive commands.

Tests should prefer mocks or fakes for Discord, YouTube, and FFmpeg.

## Documentation Requirements

The repository should keep:

- `README.md` for user-facing setup and usage.
- `TARGET.md` for high-level future-session context.
- `SPEC.md` for expected behavior and development requirements.

When major features are added or removed, `TARGET.md` and `SPEC.md` should be updated.

## Recommended Roadmap

### Phase 1: Stabilize Existing Behavior

- Fix broken text encoding in Discord messages.
- Add permission checks for sensitive commands.
- Replace silent exception handling with logged errors.
- Centralize configuration values.
- Extract shared `yt-dlp` options.
- Keep watcher-managed `yt-dlp` refresh configurable and failure-tolerant.

### Phase 2: Improve Testability

- Add unit tests for queue and playback behavior.
- Add tests for webhook signature verification.
- Reduce import-time side effects where practical.

### Phase 3: Clean Architecture

- Separate Discord command adapters from playback logic.
- Keep Socket.IO dashboard handlers thin.
- Clarify boundaries between cogs, core services, and dashboard routes.
- Move runtime/generated data into clearly documented paths.

### Phase 4: Optional Feature Decisions

- Decide the future of the voice assistant.
- Decide whether Yordle and utility features remain core or optional.
- Decide whether the dashboard should remain local-only or gain authentication.

## Acceptance Criteria For Future Implementation Work

A future change should be considered acceptable when:

- It preserves the current personal music-bot workflow.
- It does not break existing `?` commands unless intentionally migrated.
- It does not expose secrets or runtime files.
- It has focused tests when playback, queue, utility, assistant, or security behavior changes.
- It updates documentation when user-facing behavior changes.
