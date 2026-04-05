PRIORITY_AREAS = "גבעתיים (Givatayim), גוש דן (Gush Dan), המרכז (central Israel)"

PRIORITY_SCALE = """Priority levels:
- high: גבעתיים or a named גוש דן / המרכז city is **explicitly stated** as an affected area or required to take shelter. Generic nationwide alerts, nearby regions (שרון, שפלה, בקעה), or urgency wording alone are NOT enough for high.
- warning: Active home-front threat where the affected area is unconfirmed or still being clarified. NOT warning once scope is explicitly established as entirely outside the priority areas.
- informational: Threat explicitly at a named city in גוש דן / המרכז (e.g. רמת גן, פתח תקווה, הרצליה, בני ברק) that is NOT גבעתיים.
- none: Unqualified — not relevant or scope is outside the priority areas."""

DISQUALIFIERS = """NOT qualified (set qualified=false, priority=none) when ANY of these apply:
- News/wire report, journalist attribution (רויטרס, AP, כתב, דיווח), analyst or diplomatic commentary, political/legal/diplomatic news (court rulings, statements, sanctions), strategic threats framed as news.
- Story coverage or documentation (e.g. "תיעוד").
- Past event report: something that already happened (e.g. "הנפילה", "במטח האחרון", past-tense explosions, impacts, or interceptions). "הותר לפרסום" (military publication clearance) of a past impact is still a past event — geographic relevance does NOT override this rule.
- All-clear / safe to leave shelter (ניתן לצאת, סיום חובת שהייה במרחב מוגן).
- Live-index header ("אזעקות כעת", "שיגורים כעת") without explicit instructions targeting the priority areas.
- Threat explicitly limited to areas outside the priority areas (e.g. נגב, צפון, גולן, גליל, אילת, ירושלים, השפלה).
- City hard override: the update names specific cities and NONE of them are priority area cities — set qualified=false, priority=none regardless of urgency wording."""

FAITHFULNESS = """Faithfulness — CRITICAL:
- State ONLY facts present in the provided text. NEVER add, infer, or embellish.
- Hebrew only. Concise, self-contained, no emojis.
- Rephrase in your own words — never pass text verbatim."""

FIRST_PROMPT = f"""You classify messages from Israeli Telegram news channels about home-front security events.

Priority areas: {PRIORITY_AREAS}.

Decide if the message describes an active or imminent missile/rocket threat that could affect the priority areas.

{DISQUALIFIERS}

When none of the above apply, the message qualifies if it describes an active threat pipeline for the home front (launch in progress, imminent strike, civil-defense instructions) that is not explicitly limited to areas outside the priority areas.

If parent message context is provided, use it to disambiguate geography and scope before classifying.

{PRIORITY_SCALE}

{FAITHFULNESS}

subject: Short Hebrew headline (max 6 words) when qualified=true AND priority=high. Empty string otherwise.

Reply with a single JSON object only:
{{"response_message": string, "qualified": boolean, "priority": "none"|"informational"|"warning"|"high", "subject": string}}"""

ONGOING_PROMPT = f"""You manage an open Israeli home-front incident alert for a family in the priority areas.

Priority areas: {PRIORITY_AREAS}.

You will receive:
- The existing update (the narrative the family currently sees)
- The existing incident priority
- A new incoming message (with optional parent message context)
- Optionally: authoritative source messages (ground-truth timeline)

Your decisions:

1 - related — Is the new message part of the same operational incident (same salvo, scope refinement, shelter instructions, interception outcome)?
    Open-incident scope thread (CRITICAL): The incident is already open. Set related=true when the new line refines the same live threat (same salvo/launch thread): clearer destination or region (including נגב, צפון, cities, ETA, arrival timing, siren timing, or “מיקוד”). Lines that name areas outside the priority areas still belong to this thread if they clarify where the ongoing threat applies — do NOT set related=false only because a standalone opener would be disqualified for naming נגב/צפון/etc. Fold those facts into response_message; then use step 3–4 for ended/qualified.
    Unrelated content: Set related=false only when the new message is clearly a different story (news wire, past event, political commentary, foreign desk) per the disqualification list below — evaluated as editorial nature, not as geography of a refinement line.
    Mentioning Iran, launches, or security terms does not by itself prove relation — but geographic/ETA refinements to the same salvo always relate.
    Note: Stating launch origin (שיגורים מלבנון, מאיראן) with ongoing home-front framing is operational reporting, not foreign news.

2 - response_message — The merged narrative for the family.

3 - ended — Has the incident ended?
    True when: all-clear or safe to leave shelter; scope confirmed entirely outside priority areas (narrowed to צפון, נגב, שפלה, etc.); no remaining active danger.
    close_reason: "all_clear" or "out_of_subscriber_areas" as appropriate. Null when ended=false.

4 - qualified / priority — Classification of the combined situation.
    When ended=true → qualified=false, priority=none.
    When related=false → ended=false, qualified=false, priority=none. Keep response_message as the existing update text unchanged.
    Qualification lock: classify the **combined** situation after the merge. Re-run every DISQUALIFIERS check on that combined picture. If the family-facing narrative still describes a threat whose scope is **only** outside the priority areas, qualified MUST be false and priority MUST be none — including when the new line is noise, a duplicate, or a source edit that drops operational content. You MUST NOT set qualified=true or raise priority just because the previous JSON turn did something different; each merge is a full re-classification.
    Monotonicity for out-of-scope scope: if the existing update already established that impact or shelter applies only outside גבעתיים / גוש דן / המרכז, a later message that adds no new facts placing the threat inside those areas MUST NOT increase priority (e.g. must not go from none back to warning) and MUST keep qualified=false unless DISQUALIFIERS allow qualification again.

{DISQUALIFIERS}

{PRIORITY_SCALE}

Merge rules:
- Unify into one concise Hebrew narrative covering both the existing and new information.
- NEVER drop facts from the existing update unless the new message explicitly corrects or supersedes them.
- NEVER invent facts not present in either the existing update or the new message.
- When ending: append resolution to the existing narrative — do not erase what happened.
- Source edits: the post-edit authoritative source lines override earlier wording. If an edit replaces alert text with non-alert filler, strip that channel’s contribution from the operational picture; rebuild response_message from the remaining authoritative sources only; do not resurrect threat details from the old unified text that no longer appear in any source line.

{FAITHFULNESS}

subject: Hebrew headline (max 6 words) only when qualified=true AND priority=high AND existing incident priority was NOT already high. Empty string otherwise.

Reply with a single JSON object only:
{{"response_message": string, "qualified": boolean, "priority": "none"|"informational"|"warning"|"high", "related": boolean, "ended": boolean, "close_reason": string|null, "subject": string}}"""

REPROCESS_AFTER_DELETION_PROMPT = f"""You manage an open Israeli home-front incident alert for a family in the priority areas.

Priority areas: {PRIORITY_AREAS}.

One or more source messages were removed from Telegram (deleted). They must no longer influence the narrative.

You will receive:
- The existing update text the family currently sees (may be partially obsolete)
- The existing incident priority
- The remaining authoritative source messages only (ground truth)

Rebuild the incident from scratch using ONLY the remaining source lines. Treat the existing update as a hint that may be wrong; the sources are authoritative.

{DISQUALIFIERS}

{PRIORITY_SCALE}

Rules:
- response_message — One concise Hebrew narrative reflecting ONLY facts still present in the remaining sources.
- related — Always true (this is a correction pass, not a new thread).
- ended — true only if the remaining sources alone contain a real closure signal (all-clear, scope entirely outside priority areas). Otherwise false.
- When ended=true → qualified=false, priority=none, close_reason as appropriate.
- When ended=false → qualified=true if any remaining source supports an active incident, with priority from the combined remaining scope.

{FAITHFULNESS}

subject: Hebrew headline (max 6 words) only when qualified=true AND priority=high AND the rebuilt incident warrants high priority. Empty string otherwise.

Reply with a single JSON object only:
{{"response_message": string, "qualified": boolean, "priority": "none"|"informational"|"warning"|"high", "related": boolean, "ended": boolean, "close_reason": string|null, "subject": string}}"""


CLOSED_INCIDENT_SUBJECT_PROMPT = """A home-front incident alert has been closed. You receive the full Hebrew text shown to the family across all updates.

Write one very short Hebrew sentence (max 12 words) summarizing the incident: geographic focus, what happened, and outcome. Do not invent facts. No emojis.

Close reason: {close_reason_code}
Close reason label: {close_reason_label}

Reply with a single JSON object: {{"subject": string}}. Use empty string if nothing useful to summarize."""

SOURCE_EDIT_ADDENDUM = (
    "Source-edit rules for this turn:\n"
    "This message is an EDIT of a previously counted source. "
    "The authoritative source lines are the post-edit truth.\n"
    "- Rebuild response_message from authoritative sources. "
    "Drop facts that existed only in the pre-edit version and no longer appear.\n"
    "- Default to related=true unless the edit introduces a clearly separate event.\n"
    "- If the post-edit text is personal filler, apology, or channel noise with no "
    "operational civil-defense content, treat it like a removed alert line: keep "
    "qualified=false and priority=none; derive the narrative only from other sources; "
    "never re-qualify or raise priority from the old unified text alone.\n"
    "- After any source edit, re-apply DISQUALIFIERS to the combined scope: if the "
    "situation remains entirely outside the priority areas, qualified MUST stay false.\n"
    "- Keep ended=false unless the post-edit text contains a real closure signal "
    "(all-clear, safe to leave shelter, scope confirmed outside priority areas). "
    "Origin or wording corrections alone are NOT closure."
)


def build_user_message(
    event_message: str,
    parent_message: str | None = None,
) -> str:
    if parent_message:
        return (
            f"parent message for context: {parent_message}\n"
            f"new update: {event_message}"
        )
    return event_message


def build_first_prompt(
    recent_closure_appendix: str | None = None,
) -> str:
    if recent_closure_appendix:
        return f"{FIRST_PROMPT}\n\n{recent_closure_appendix}"
    return FIRST_PROMPT


def build_ongoing_prompt(
    existing_update: str,
    existing_priority: str,
    source_messages_context: str | None = None,
    is_source_edit: bool = False,
    edited_message_previous_text: str | None = None,
) -> str:
    parts: list[str] = [
        ONGOING_PROMPT,
        f"\nThe existing update: '{existing_update}'",
        f"The existing incident priority: '{existing_priority}'",
    ]
    if source_messages_context and source_messages_context.strip():
        parts.append(
            f"\nAuthoritative source messages (latest versions only):\n"
            f"{source_messages_context.strip()}\n"
            f"Treat these as the ground-truth timeline."
        )
    if is_source_edit:
        parts.append(f"\n{SOURCE_EDIT_ADDENDUM}")
        if edited_message_previous_text and edited_message_previous_text.strip():
            parts.append(
                f"\nPrevious text of the edited source (now superseded):\n"
                f"{edited_message_previous_text.strip()}"
            )
    return "\n".join(parts)


def build_reprocess_after_deletion_prompt(
    existing_update: str,
    existing_priority: str,
    source_messages_context: str,
) -> str:
    parts: list[str] = [
        REPROCESS_AFTER_DELETION_PROMPT,
        f"\nThe existing update (may be partially obsolete): '{existing_update}'",
        f"The existing incident priority: '{existing_priority}'",
    ]
    if source_messages_context and source_messages_context.strip():
        parts.append(
            "\nRemaining authoritative source messages only:\n"
            f"{source_messages_context.strip()}\n"
        )
    else:
        parts.append("\nRemaining authoritative source messages: (none)")
    return "\n".join(parts)


def build_closed_subject_prompt(
    close_reason_code: str,
    close_reason_label_text: str,
) -> str:
    return CLOSED_INCIDENT_SUBJECT_PROMPT.format(
        close_reason_code=close_reason_code,
        close_reason_label=close_reason_label_text,
    )
