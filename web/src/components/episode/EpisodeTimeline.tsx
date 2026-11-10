"use client";

import { MoneyText } from "@/components/ui";
import type { EpisodeTimelineEventOut } from "@/lib/types";
import styles from "./EpisodeTimeline.module.css";
import { EpisodeEvidence } from "./EpisodeEvidence";

interface Props {
  timeline: EpisodeTimelineEventOut[];
  currency: string;
  caseId: string;
}

export function EpisodeTimeline({ timeline, currency, caseId }: Props) {
  if (!timeline.length) {
    return <p className={styles.empty}>No chronological events recorded yet for this care episode.</p>;
  }

  return (
    <div className={styles.timelineContainer}>
      <ol className={styles.timelineList}>
        {timeline.map((event) => {
          const toneClass = styles[event.status_tone] || styles.neutral;
          const typeClass = styles[event.event_type] || "";

          return (
            <li key={event.id} className={styles.timelineItem}>
              <span className={`${styles.timelineMarker} ${toneClass}`} aria-hidden="true" />
              <div className={styles.contentCard}>
                <div className={styles.eventHeader}>
                  {event.event_date ? <time className={styles.dateBadge} dateTime={event.event_date}>{event.event_date}</time> : <span className={styles.dateBadge}>Date unknown</span>}
                  <span>{event.date_basis.replaceAll("_", " ")}</span>
                  <span className={`${styles.typeBadge} ${typeClass}`}>
                    {event.event_type.replace(/_/g, " ")}
                  </span>
                </div>
                <h4 className={styles.eventTitle}>{event.title}</h4>
                <p className={styles.eventDetail}>{event.detail}</p>
                {event.flag_id && <a href={`#question-${event.flag_id}`}>Review billing question</a>}
                {!!event.sources.length && <details><summary>Supporting evidence</summary><EpisodeEvidence sources={event.sources} caseId={caseId} documentId={event.document_id ?? undefined} /></details>}
                {event.amount ? (
                  <div className={styles.amountTag}>
                    Amount: <MoneyText value={event.amount} currency={event.currency || currency} />
                  </div>
                ) : null}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

