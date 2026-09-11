-- Lich su chat cua CLIProxy, gom theo phien.
--
-- Chay tren instance derp-postgres o vpn6, trong database `derp`.
--
-- Vi sao dung chinh database `derp` chu khong tao database rieng: dashboard
-- (derp-backend) da noi san vao `derp` bang mot pool duy nhat. Mot database
-- rieng buoc dashboard phai mo them ket noi thu hai chi de doc lich su. Schema
-- rieng cho ta su tach bach can thiet ma khong tra gia do.
--
-- Vi sao khong dat o vpn4: vpn4 khong co Postgres nao (do 2026-09-09; chi co
-- opencode-pg-tunnel tro sang day), va no la may chay DERP relay cho ca fleet -
-- them du lieu co trang thai vao do la them thu phai sao luu va khoi phuc moi
-- lan chuyen server.
--
-- Idempotent: chay lai nhieu lan khong hong.

BEGIN;

CREATE SCHEMA IF NOT EXISTS chat_history;

-- Mot phien = mot cuoc hoi thoai lien tuc cua client.
--
-- session_key lay tu header X-Session-Id do chinh client gui. Do tren 14 ngay
-- luu luong that: 481/481 request co header nay, 30 phien, trung binh 16 luot,
-- phien dai nhat trai 72.9 gio. Client nao khong gui thi logger sinh khoa
-- sess_anon_<hash> theo ngay.
CREATE TABLE IF NOT EXISTS chat_history.chat_sessions (
  id            BIGSERIAL PRIMARY KEY,
  session_key   TEXT        NOT NULL UNIQUE,
  first_seen_at TIMESTAMPTZ NOT NULL,
  last_seen_at  TIMESTAMPTZ NOT NULL,
  turn_count    INT         NOT NULL DEFAULT 0,
  client_ua     TEXT,
  models        TEXT[]      NOT NULL DEFAULT '{}'
);

-- Mot luot = mot request/response di qua proxy.
--
-- request_body la TEXT chu KHONG phai JSONB: than request bi cat o tran capture
-- khong con la JSON hop le, va than da giai nen that bai duoc tra ve dang tho
-- nen co the chua byte NUL - Postgres tu choi U+0000 trong ca text lan jsonb.
-- request_json chi duoc dien khi than thuc su parse duoc, de van truy van duoc
-- theo truong khi can.
CREATE TABLE IF NOT EXISTS chat_history.chat_turns (
  id            BIGSERIAL   PRIMARY KEY,
  session_id    BIGINT      NOT NULL REFERENCES chat_history.chat_sessions(id) ON DELETE CASCADE,
  request_id    TEXT,
  created_at    TIMESTAMPTZ NOT NULL,
  model         TEXT,
  uri           TEXT,
  status_code   INT,
  streaming     BOOL        NOT NULL DEFAULT FALSE,
  duration_ms   BIGINT,
  ttfb_ms       BIGINT,
  request_body  TEXT,
  request_json  JSONB,
  response_text TEXT,
  usage         JSONB,
  error_text    TEXT,
  truncated     BOOL        NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS chat_turns_session_created_idx
  ON chat_history.chat_turns (session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS chat_turns_created_idx
  ON chat_history.chat_turns (created_at DESC);
CREATE INDEX IF NOT EXISTS chat_sessions_last_seen_idx
  ON chat_history.chat_sessions (last_seen_at DESC);

COMMIT;

-- Quyen: cliproxy chi duoc ghi vao schema nay, khong cham vao bang cua derp.
--
-- Tao role bang khoi DO vi CREATE ROLE khong co IF NOT EXISTS. Mat khau duoc
-- dat rieng luc deploy (ALTER ROLE ... PASSWORD), khong nam trong file nay.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cliproxy_chat') THEN
    CREATE ROLE cliproxy_chat LOGIN;
  END IF;
END
$$;

GRANT USAGE ON SCHEMA chat_history TO cliproxy_chat;

-- Proxy goi ten bang KHONG kem schema trong ban build dau tien, nen role phai
-- tim thay bang o chat_history. Thieu dong nay: moi lan ghi deu hong voi
-- `relation "chat_sessions" does not exist` (do duoc 2026-09-10 tren prod).
ALTER ROLE cliproxy_chat SET search_path = chat_history, public;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA chat_history TO cliproxy_chat;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA chat_history TO cliproxy_chat;

-- Bang tao sau nay cung theo quyen tren.
ALTER DEFAULT PRIVILEGES IN SCHEMA chat_history
  GRANT SELECT, INSERT, UPDATE ON TABLES TO cliproxy_chat;
ALTER DEFAULT PRIVILEGES IN SCHEMA chat_history
  GRANT USAGE, SELECT ON SEQUENCES TO cliproxy_chat;

-- Dashboard doc bang chinh user `derp` da co san, khong can them ket noi.
-- (User `derp` la chu so huu schema nen da du quyen.)
