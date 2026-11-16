/** Types of the JSON API — see docs/DESIGN-v2.md, "HTTP API (JSON)". */

export type StatusCode = 'sent' | 'reject' | 'deferred' | 'bounced' | 'multiple' | 'unknown';
export const STATUS_CODES: readonly StatusCode[] = ['sent', 'deferred', 'bounced', 'reject', 'multiple', 'unknown'];

export interface Status {
  code: StatusCode | string;
  message?: string | null;
}

export interface Relay {
  host?: string | null;
  ip?: string | null;
  port?: number | string | null;
}

export interface Client {
  host?: string | null;
  ip?: string | null;
}

export interface Recipient {
  to: string;
  orig_to?: string | null;
  status?: Status | null;
  relay?: Relay | null;
  dsn?: string | null;
  delay?: number | null;
  delays?: string | null;
  timestamp?: string | null;
}

export interface LogLine {
  timestamp: string;
  queue_id?: string | null;
  message: string;
}

export interface Email {
  id: string;
  queue_id?: string | null;
  host?: string | null;
  timestamp?: string | null;
  first_attempt?: string | null;
  last_attempt?: string | null;
  mail_from?: string | null;
  mail_to?: string | null;
  mail_to_alias?: Record<string, string> | null;
  recipients?: Recipient[] | null;
  subject?: string | null;
  size?: number | string | null;
  message_id?: string | null;
  status?: Status | null;
  /** more than one distinct recipient (new documents; legacy ones use status `multiple`) */
  multiple?: boolean | null;
  /** representative relay: worst failed delivery, else the last network hand-off */
  relay?: Relay | null;
  client?: Client | null;
  sasl_method?: string | null;
  sasl_username?: string | null;
  service?: string | null;
  dsn?: string | null;
  delay?: number | null;
  nrcpt?: number | null;
  dkim?: { domain?: string | null; selector?: string | null } | null;
  tls?: boolean | null;
  lines?: LogLine[];
}

export interface EmailList {
  error: boolean;
  result: Email[];
  count: number;
  remaining: number;
  page: number;
  total_pages: number;
}

export interface SessionConfig {
  mta?: string;
  mail_domain?: string;
  default_limit?: number;
  max_limit?: number;
  housekeeping_days?: number;
  datetime_format?: string;
  gui_max_log_period?: number;
  exclude_from_top_senders?: string[];
  exclude_from_top_recipients?: string[];
}

export interface Session {
  authenticated: boolean;
  login: string | null;
  auth_mode: 'local' | 'ldap';
  needs_setup: boolean;
  version: string;
  config: SessionConfig;
}

export interface Facets {
  hosts: string[];
  statuses: string[];
  services: string[];
}

export interface TopSender {
  mail_from: string;
  count: number;
}
export interface TopRecipient {
  mail_to: string;
  count: number;
}
export interface TopRelay {
  relay: string;
  count: number;
}
export interface HostStats {
  host: string;
  count: number;
  sent: number;
  deferred: number;
  bounced: number;
  reject: number;
}
export interface TimelinePoint {
  t: string;
  sent: number;
  deferred: number;
  bounced: number;
  reject: number;
  other: number;
}

export interface User {
  login: string;
}
