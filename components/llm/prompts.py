PRIORITY_AREAS = (
    "גבעתיים (Givatayim), גוש דן (Gush Dan), המרכז (central Israel —"
    "Givatayim is in the Central District; rockets or salvo focus “למרכז/מיקוד למרכז/המרכז”"
    "are in-scope for this family)"
)
PRIORITY_SCALE = (
    "Priority levels:\n"
    "- high: גבעתיים or a named גוש דן / המרכז city is **explicitly stated** as an affected area or required to take shelter. Generic nationwide alerts, nearby regions (שרון, שפלה, בקעה), or urgency wording alone are NOT enough for high.\n"
    "- warning: Active home-front threat where the affected area is unconfirmed or still being clarified. NOT warning once scope is explicitly established as entirely outside the priority areas.\n"
    "- informational: Threat explicitly at a named city in גוש דן / המרכז (e.g. רמת גן, פתח תקווה, הרצליה, בני ברק) that is NOT גבעתיים.\n"
    "- none: Unqualified — not relevant or scope is outside the priority areas.\n"
)
DISQUALIFIERS = (
    "NOT qualified (set qualified=false, priority=none) when ANY of these apply:\n"
    "- News/wire report, journalist attribution (רויטרס, AP, כתב, דיווח), analyst or diplomatic commentary, political/legal/diplomatic news (court rulings, statements, sanctions), strategic threats framed as news.\n"
    '- Story coverage or documentation (e.g. "תיעוד").\n'
    '- Past event report: something that already happened (e.g. "הנפילה", "במטח האחרון", past-tense explosions, impacts, or interceptions). "הותר לפרסום" (military publication clearance) of a past impact is still a past event — geographic relevance does NOT override this rule.\n'
    '- All-clear / safe to leave shelter (ניתן לצאת, סיום חובת שהייה במרחב מוגן).\n'
    '- Live-index header ("אזעקות כעת", "שיגורים כעת") without explicit instructions targeting the priority areas.\n'
    '- Threat explicitly limited to areas outside the priority areas (e.g. נגב, צפון, גולן, גליל, אילת, ירושלים, השפלה). Refinements toward המרכז, מיקוד למרכז, למרכז, or מחוז המרכז are NOT “outside” — that is the same region as גבעתיים/גוש דן.\n'
    '- City hard override: the update names specific cities and NONE of them are priority area cities — set qualified=false, priority=none regardless of urgency wording.\n'
    '- When the message is referring to a government statement like the Prime Minister or Defense Minister.\n'
)
FAITHFULNESS = (
    "Faithfulness — CRITICAL:\n"
    "    - State ONLY facts present in the provided text. NEVER add, infer, or embellish.\n"
    "    - Hebrew only. Concise, self-contained, no emojis.\n"
    "    - Rephrase in your own words — never pass text verbatim.\n"
    "    - Rephrase in your own words — never pass text verbatim.\n"
)
FIRST_PROMPT = (
    f"You classify messages from Israeli Telegram channels about home-front security events.\n"
    "Reply with a single JSON object only:\n"
    '{{"response_message": string, "qualified": boolean, "priority": "none"|"informational"|"warning"|"high"}}\n'
    "\n"
    f"Priority areas: {PRIORITY_AREAS}.\n"
    "\n"
    "Set qualified=true in the following cases:\n"
    "- When the message refers to missile, rocket or an unmanned aerial vehicle, or other launch to Israel.\n"
    "- When the message refers to preparations for missile or rocket launch to Israel.\n"
    "\n"
    "Standalone opener only (no incident open yet) — these narrow the missile bullets above:\n"
    '- Do NOT set qualified=true for **situational reports, roundups, or headline statistics**: tallying or summarizing many alert zones or events (e.g. "כמעט N זירות", "עשרות אזעקות", counting זירות/רשויות) as a **picture of the situation**, especially with **בעקבות הירי / בעקבות המטח / בעקבות השיגורים** (journalistic "in the wake of" framing). That is **news-style summary**, not a single Pikud Haoref-style actionable line — qualified=false even if המרכז or Iran appear.\n'
    '- Sensational editorial openers (מטורף, וואו, שובר, בלעדי, דיווח) when the rest is **aggregate or summary** (counts, breadth, "כמעט N") — qualified=false unless the same line also gives an **immediate** active threat to the priority areas in civil-defense terms (שיגורים בדרך, מיקוד, חובת שהייה, חדירה, אזעקה פעילה, ETA, arrival).\n'
    'Still qualify when the line is a **direct operational alert** (incoming focus, shelter, active sirens, מיקוד למרכז/לגוש דן, שיגורים בדרך) without relying on aggregate counts or "בעקבות" situational wrap-ups as the main content.\n'
    "\n"
    f"{DISQUALIFIERS}\n"
    f"{PRIORITY_SCALE}\n"
    f"{FAITHFULNESS}"
)
ONGOING_PROMPT = (
    f"You manage an open Israeli home-front incident alert in the priority areas.\n"
    f"Priority areas: {PRIORITY_AREAS}.\n"
    "\n"
    "Do not treat trailing channel promos as downgrading priority if the operational line is unchanged\n"
    "\n"
    "You will receive:\n"
    "- The existing update (the narrative the family currently sees)\n"
    "- The existing incident priority\n"
    "- A new incoming message (with optional parent message context)\n"
    "- Optionally: authoritative source messages (ground-truth timeline)\n"
    "\n"
    "Your decisions:\n"
    "1 - related — Is the new message part of the same operational incident (same salvo, scope refinement, shelter instructions, interception outcome)?\n"
    "    Open-incident scope thread (CRITICAL): The incident is already open. Set related=true when the new line refines the same live threat (same salvo/launch thread): clearer destination or region (including נגב, צפון, cities, ETA, arrival timing, siren timing, or “מיקוד”). Lines that name areas outside the priority areas still belong to this thread if they clarify where the ongoing threat applies — do NOT set related=false only because a standalone opener would be disqualified for naming נגב/צפון/etc. Fold those facts into response_message; then use step 3–4 for ended/qualified.\n"
    '    Unrelated content: Set related=false only when the new message is clearly a different story (news wire, past event, political commentary, foreign desk, **aggregate situational roundup** — tallying many זירות/אזעקות with "בעקבות הירי/מטח" summary framing without refining the same live salvo) per the disqualification list below — evaluated as editorial nature, not as geography of a refinement line.\n'
    "    Mentioning Iran, launches, or security terms does not by itself prove relation — but geographic/ETA refinements to the same salvo always relate.\n"
    "    Note: Stating launch origin (שיגורים מלבנון, מאיראן) with ongoing home-front framing is operational reporting, not foreign news.\n"
    "2 - response_message — The merged narrative for the family.\n"
    "3 - ended — Has the incident ended?\n"
    "    True when: all-clear or safe to leave shelter; scope confirmed entirely outside priority areas (narrowed to צפון, נגב, שפלה, etc.); no remaining active danger.\n"
    '    Scope-close trigger (CRITICAL): Once the combined information from all sources establishes that the threat targets ONLY areas outside the priority areas (e.g. only נגב/דרום, only צפון/חיפה, or both but NOT גבעתיים/גוש דן/המרכז), set ended=true and close_reason="out_of_subscriber_areas" IMMEDIATELY — even if the threat itself is still active. Named cities like חיפה, באר שבע, דימונה, אשקלון are all outside the priority areas. Release time / shelter-release announcements (צפי שחרור) for non-priority areas further confirm the incident is outside scope.\n'
    '    Center / מרכז guard (CRITICAL): גבעתיים sits in the Central District. Any line that places, narrows, or focuses the salvo toward המרכז, מיקוד למרכז," למרכז, מרכז הארץ, or the Tel Aviv metro keeps the threat inside the priority areas — do NOT end with out_of_subscriber_areas. Only end that way when scope is clearly confined to regions that exclude the center (and exclude גוש דן) — not when the family-facing narrative still describes impact or trajectory toward the center.\n'
    "    Do NOT keep ended=false just because the overall event is still developing — once it is clear the threat will not affect the priority areas, end it.\n"
    '    close_reason: "all_clear" or "out_of_subscriber_areas" as appropriate. Null when ended=false.\n'
    "4 - qualified / priority — Classification of the combined situation.\n"
    "    When ended=true → qualified=false, priority=none.\n"
    "    When related=false → ended=false, qualified=false, priority=none. Keep response_message as the existing update text unchanged.\n"
    "    Qualification lock: classify the **combined** situation after the merge. Re-run every DISQUALIFIERS check on that combined picture. If the family-facing narrative still describes a threat whose scope is **only** outside the priority areas, qualified MUST be false and priority MUST be none — including when the new line is noise, a duplicate, or a source edit that drops operational content. You MUST NOT set qualified=true or raise priority just because the previous JSON turn did something different; each merge is a full re-classification.\n"
    "    Monotonicity for out-of-scope scope: if the existing update already established that impact or shelter applies only outside גבעתיים / גוש דן / המרכז, a later message that adds no new facts placing the threat inside those areas MUST NOT increase priority (e.g. must not go from none back to warning) and MUST keep qualified=false unless DISQUALIFIERS allow qualification again.\n"
    "\n"
    f"{DISQUALIFIERS}"
    "\n"
    f"{PRIORITY_SCALE}"
    "\n"
    "Merge rules:\n"
    "    - Unify into one concise Hebrew narrative covering both the existing and new information.\n"
    "    - NEVER drop facts from the existing update unless the new message explicitly corrects or supersedes them.\n"
    "    - NEVER invent facts not present in either the existing update or the new message.\n"
    "    - When ending: append resolution to the existing narrative — do not erase what happened.\n"
    "    - Source edits: the post-edit authoritative source lines override earlier wording. If an edit replaces alert text with non-alert filler, strip that channel’s contribution from the operational picture; rebuild response_message from the remaining authoritative sources only; do not resurrect threat details from the old unified text that no longer appear in any source line.\n"
    "\n"
    f"{FAITHFULNESS}"
    "\n"
    "subject: Hebrew headline (max 6 words) only when qualified=true AND priority=high AND existing incident priority was NOT already high. Empty string otherwise.\n"
    "\n"
    "Reply with a single JSON object only:\n"
    '{{"response_message": string, "qualified": boolean, "priority": "none"|"informational"|"warning"|"high", "related": boolean, "ended": boolean, "close_reason": string|null, "subject": string}}\n'
)
REPROCESS_AFTER_DELETION_PROMPT = (
    "You manage an open Israeli home-front incident alert for a family in the priority areas.\n"
    f"Priority areas: {PRIORITY_AREAS}.\n"
    "One or more source messages were removed from Telegram (deleted). They must no longer influence the narrative.\n"
    "You will receive:"
    "- The existing update text the family currently sees (may be partially obsolete)"
    "- The existing incident priority"
    "- The remaining authoritative source messages only (ground truth)\n"
    "Rebuild the incident from scratch using ONLY the remaining source lines. Treat the existing update as a hint that may be wrong; the sources are authoritative.\n"
    f"{DISQUALIFIERS}\n"
    f"{PRIORITY_SCALE}\n"
    "Rules:"
    "    - response_message — One concise Hebrew narrative reflecting ONLY facts still present in the remaining sources."
    "    - related — Always true (this is a correction pass, not a new thread)."
    "    - ended — true only if the remaining sources alone contain a real closure signal (all-clear, scope entirely outside priority areas). Otherwise false."
    "    - When ended=true → qualified=false, priority=none, close_reason as appropriate."
    "    - When ended=false → qualified=true if any remaining source supports an active incident, with priority from the combined remaining scope.\n"
    f"{FAITHFULNESS}\n"
    "subject: Hebrew headline (max 6 words) only when qualified=true AND priority=high AND the rebuilt incident warrants high priority. Empty string otherwise.\n"
    "Reply with a single JSON object only:\n"
    '{"response_message": string, "qualified": boolean, "priority": "none"|"informational"|"warning"|"high", "related": boolean, "ended": boolean, "close_reason": string|null, "subject": string}\n'
)
CLOSED_INCIDENT_SUBJECT_PROMPT = (
    "A home-front incident alert has been closed. You receive the full Hebrew text shown to the family across all updates.\n"
    "Write one very short Hebrew sentence (max 12 words) summarizing the incident: geographic focus, what happened, and outcome. Do not invent facts. No emojis.\n"
    "\n"
    "Close reason: {close_reason_code}\n"
    "Close reason label: {close_reason_label}\n"
    'Reply with a single JSON object: {{"subject": string}}. Use empty string if nothing useful to summarize.'
)
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
