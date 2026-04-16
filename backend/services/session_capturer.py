import asyncio
import logging
import time
import os
from typing import Optional
from backend.core.account_pool import AccountPool, Account

log = logging.getLogger("qwen2api.capturer")

class CaptureSession:
    def __init__(self):
        self.page = None
        self.active = False
        self.current_provider = None
        log.info("[Capturer] Initialized session capturer service (DrissionLite)")

    async def launch(self, provider: str = "qwen"):
        if self.active:
            await self.stop()

        from DrissionPage import ChromiumPage, ChromiumOptions
        import os
        
        log.info("[Capturer] Step 1: Initializing DrissionPage for Qwen (Visible Mode)...")
        try:
            import random, shutil
            # Configure a brand NEW isolated Chrome window (popup)
            co = ChromiumOptions()
            co.headless(False)
            co.set_argument('--no-sandbox')
            co.set_argument('--disable-gpu')
            co.set_argument('--start-maximized')
            co.new_env(True)  # Force a completely new Chrome process
            
            # Random port so it never conflicts with user's own Chrome
            port = random.randint(19200, 19999)
            co.set_local_port(port)
            
            # Unique profile per session to avoid lock conflicts
            base_profiles = os.path.join(os.getcwd(), "data", "browser_profiles")
            capture_profile = os.path.join(base_profiles, f"capture_{port}")
            # Clean any stale profile
            if os.path.exists(capture_profile):
                try:
                    shutil.rmtree(capture_profile, ignore_errors=True)
                except Exception:
                    pass
            os.makedirs(capture_profile, exist_ok=True)
            co.set_user_data_path(capture_profile)
            self._profile_path = capture_profile

            log.info("[Capturer] Step 2: Launching physical browser window...")
            def _launch():
                return ChromiumPage(co)

            self.page = await asyncio.to_thread(_launch)
            target_url = "https://chat.qwen.ai"
            self.current_provider = "qwen"
            
            log.info(f"[Capturer] Step 3: Navigating to {target_url}...")
            self.page.get(target_url)
            
            log.info("[Capturer] Step 4: Window visible. Activating session.")
            self.active = True
            return {"ok": True, "message": "Navegador Qwen aberto com sucesso. Realize o login na janela que apareceu."}
        except Exception as e:
            log.error(f"[Capturer] CRITICAL failure during Drission launch: {e}", exc_info=True)
            await self.stop()
            return {"ok": False, "message": f"Erro ao abrir janela visual: {str(e)}"}

    async def extract(self, pool: AccountPool):
        if not self.active or not self.page:
            return {"ok": False, "message": "Nenhum navegador de captura ativo."}

        try:
            log.info(f"[Capturer] Extracting {self.current_provider} data via Drission...")
            
            # Run all synchronous DrissionPage calls in a thread to avoid blocking
            def _do_extract():
                page = self.page
                provider = self.current_provider
                
                token = None
                email = None
                username = "Manual Capture"
                cookies_domain = "qwen.ai"
                
                # Re-read the current page URL to confirm browser is alive
                try:
                    current_url = page.url
                    log.info(f"[Capturer] Browser is alive at: {current_url}")
                except Exception as e:
                    return {"ok": False, "message": f"Navegador desconectado: {str(e)}"}
                
                if provider == "qwen":
                    token = page.run_js('return localStorage.getItem("token");')
                    try:
                        user_info = page.run_js('''
                            async function getInfo() {
                                const res = await fetch('/api/v1/auths/', {
                                    headers: { 'Authorization': 'Bearer ' + localStorage.getItem('token') }
                                });
                                return res.ok ? await res.json() : {};
                            }
                            return await getInfo();
                        ''')
                        email = user_info.get("email") or f"q_captured_{int(time.time())}@qwen.ai"
                        username = user_info.get("name") or "Qwen User"
                    except Exception:
                        email = f"q_captured_{int(time.time())}@qwen.ai"
                        username = "Qwen User"
                
                if not token:
                    return {"ok": False, "message": "Não foi possível extrair o token do Qwen. Certifique-se de que o login foi concluído."}

                # Gather all cookies
                all_cookies = list(page.cookies())
                cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in all_cookies if cookies_domain in c.get("domain", ""))
                
                return {
                    "token": token, "email": email, "username": username,
                    "cookies": cookie_str, "ok": True
                }
            
            result = await asyncio.to_thread(_do_extract)
            
            if not result.get("ok"):
                return result
            
            account = Account(
                email=result["email"], password="", token=result["token"],
                cookies=result["cookies"], username=result["username"], valid=True
            )
            
            await pool.add(account)
            log.info(f"[Capturer] Qwen account {result['email']} captured via Drission.")
            await self.stop()
            return {"ok": True, "message": "Conta Qwen capturada com sucesso!", "email": result["email"]}
        except Exception as e:
            log.error(f"[Capturer] Extraction error: {e}", exc_info=True)
            return {"ok": False, "message": f"Erro na extração: {str(e)}"}

    async def stop(self):
        try:
            if self.page:
                self.page.quit()
        except Exception:
            pass
        # Clean up unique profile
        try:
            import shutil
            if hasattr(self, '_profile_path') and self._profile_path and os.path.exists(self._profile_path):
                shutil.rmtree(self._profile_path, ignore_errors=True)
        except Exception:
            pass
        self.page = None
        self.active = False
        self._profile_path = None
        log.info("[Capturer] Drission session stopped.")

global_capture_session = CaptureSession()
