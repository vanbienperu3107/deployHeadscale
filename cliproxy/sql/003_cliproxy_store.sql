-- Kho cau hinh + token cua CLIProxy (tinh nang PostgreSQL store, bien PGSTORE_DSN).
--
-- Chay tren instance derp-postgres o vpn6, trong database `derp`, bang user `derp`
-- (workflow migrate-cliproxy-store.yml). Idempotent: chay lai nhieu lan khong hong.
--
-- Bang (config_store, auth_store, cooldown_store) do CHINH CLIProxyAPI tao luc khoi
-- dong (CREATE TABLE IF NOT EXISTS) va do pgstore-seed.sh tao truoc khi seed. File
-- nay chi chuan bi role + schema.
--
-- VI SAO role so huu schema + search_path, va PGSTORE_SCHEMA de TRONG:
-- khi PGSTORE_SCHEMA co gia tri, CLIProxyAPI chay `CREATE SCHEMA IF NOT EXISTS` moi
-- lan khoi dong. Postgres kiem quyen CREATE tren DATABASE TRUOC khi kiem schema da
-- ton tai chua -> role khong co quyen do se bi tu choi du schema da co san. De trong
-- thi proxy dung ten bang khong kem schema, tim theo search_path ben duoi.
--
-- DU LIEU NHAY CAM: auth_store chua refresh token OAuth Claude/Codex, config_store
-- chua api-keys + provider key (Gemini/OpenAI...). Ai doc duoc schema nay = co toan
-- bo quyen goi model. Ban sao luu database `derp` tu nay cung phai giu nhu mat khau.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cliproxy_store') THEN
    -- Mat khau dat rieng luc migrate (ALTER ROLE ... PASSWORD), khong nam o day.
    CREATE ROLE cliproxy_store LOGIN;
  END IF;
END
$$;

CREATE SCHEMA IF NOT EXISTS cliproxy_store AUTHORIZATION cliproxy_store;
-- Schema co the da ton tai tu truoc voi chu khac: ep ve dung chu.
ALTER SCHEMA cliproxy_store OWNER TO cliproxy_store;
-- Chi chu schema (va superuser) duoc nhin vao. Dashboard KHONG can doc bang nay.
REVOKE ALL ON SCHEMA cliproxy_store FROM PUBLIC;

-- CHI mot schema trong search_path: neu schema bi xoa, lenh CREATE TABLE cua proxy
-- se loi ro rang thay vi am tham tao bang chua token trong `public`.
ALTER ROLE cliproxy_store SET search_path = cliproxy_store;
