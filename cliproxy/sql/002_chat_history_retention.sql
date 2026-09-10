-- Don lich su qua 90 ngay.
--
-- Chay dinh ky (cron cua workflow deploy hoac job rieng). Khong dat trong
-- proxy: proxy chi ghi, khong bao gio xoa - mot loi trong duong ghi khong duoc
-- phep bien thanh mat du lieu.
--
-- Idempotent va an toan khi chay lai.

BEGIN;

-- Xoa luot cu truoc; phien rong se bi don o buoc sau.
DELETE FROM chat_history.chat_turns
WHERE created_at < now() - INTERVAL '90 days';

-- Phien khong con luot nao thi khong con y nghia.
DELETE FROM chat_history.chat_sessions s
WHERE NOT EXISTS (
  SELECT 1 FROM chat_history.chat_turns t WHERE t.session_id = s.id
);

COMMIT;
