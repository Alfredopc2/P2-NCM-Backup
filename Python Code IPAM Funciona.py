# ipam_full_evidence.py (parche: guardar SOLO si cambia el running-config)
from netmiko import ConnectHandler
from tabulate import tabulate
import time, os, difflib, subprocess, re
from datetime import datetime

HOST = "192.168.0.161"
USER = "admin"
PASSWORD = "alfredo123"
PORT = 22

COMMANDS = [
    "show ip interface brief",
    "show ip route",
    "show ip ospf neighbor",
    "show ip ospf"
]

PING_TARGETS = ["2.2.2.2", "3.3.3.3"]

BACKUP_ROOT = "backups"
os.makedirs(BACKUP_ROOT, exist_ok=True)

# --- NUEVO: normalizar líneas volátiles del running-config ---
VOLATILE_PATTERNS = [
    r"^!.*$",                                 # comentarios que algunos IOS incluyen
    r"^Building configuration.*$",
    r"^Current configuration.*$",
    r"^Last configuration change.*$",
    r"^! Last configuration change.*$",
    r"^ntp clock-period.*$",
    r"^clock-period.*$",                      # algunos equipos
    r"^boot-start-marker.*$",
    r"^boot-end-marker.*$",
    r"^time-range .*",                        # si se usa y rota
    r"^service timestamps .*",                # marcas de tiempo en logs
    r"^spanning-tree vlan \d+ priority \d+$", # si lo tocan dinámicamente
    r"^end$"                                  # línea final que no aporta a diffs
]

def normalize_config(text: str) -> str:
    lines = []
    for line in text.splitlines():
        # filtra líneas que matchean cualquiera de los patrones volátiles
        if any(re.search(pat, line) for pat in VOLATILE_PATTERNS):
            continue
        # quita espacios de cola
        lines.append(line.rstrip())
    # colapsa múltiples líneas vacías consecutivas
    cleaned = []
    last_blank = False
    for l in lines:
        if l == "":
            if last_blank:
                continue
            last_blank = True
        else:
            last_blank = False
        cleaned.append(l)
    return "\n".join(cleaned).strip() + "\n"

def _git_push_if_needed(msg):
    try:
        # Solo comitea si hay cambios en el working tree
        subprocess.run(["git", "add", "."], check=False)
        # Si no hay cambios, 'git commit' saldrá con código != 0; lo ignoramos
        subprocess.run(["git", "commit", "-m", msg], check=False)
        subprocess.run(["git", "push"], check=False)
    except Exception:
        pass

def _last_cfg_path(folder):
    # busca el último archivo de config “_running_cfg_*.txt”
    if not os.path.isdir(folder):
        return None
    files = sorted([f for f in os.listdir(folder) if f.endswith("_running_cfg.txt")])
    return os.path.join(folder, files[-1]) if files else None

def _different_cfg(curr_norm_text: str, last_path: str) -> bool:
    if not last_path or not os.path.exists(last_path):
        return True
    with open(last_path, "r", encoding="utf-8", errors="ignore") as fb:
        prev = fb.read()
    diff = list(difflib.unified_diff(prev.splitlines(True), curr_norm_text.splitlines(True)))
    return len(diff) > 0

def run_once():
    device = {
        "device_type": "cisco_ios",
        "host": HOST,
        "username": USER,
        "password": PASSWORD,
        "port": PORT,
        "allow_agent": False,
        "use_keys": False,
        "auth_timeout": 30
    }

    print(f"Conectando a {HOST} ...")
    try:
        conn = ConnectHandler(**device)
    except Exception as e:
        print("ERROR: No se pudo conectar:", e)
        return

    # 1) OBTENER RUNNING-CONFIG Y COMPARAR (base de verdad)
    try:
        raw_cfg = conn.send_command("show running-config", delay_factor=1)
    except Exception as e:
        print("ERROR al obtener running-config:", e)
        conn.disconnect()
        return

    norm_cfg = normalize_config(raw_cfg)
    device_folder = os.path.join(BACKUP_ROOT, HOST)
    os.makedirs(device_folder, exist_ok=True)

    last_cfg_path = _last_cfg_path(device_folder)

    if _different_cfg(norm_cfg, last_cfg_path):
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

        # 2) GUARDAR NUEVO BACKUP DE CONFIG (normalizada o cruda; aquí guardamos cruda)
        cfg_path = os.path.join(device_folder, f"{HOST}_running_cfg.txt")  # siempre el “actual”
        with open(cfg_path, "w", encoding="utf-8") as f:
            f.write(norm_cfg)  # puedes cambiar a raw_cfg si prefieres crudo; la comparación ya fue con norm_cfg

        # 3) (OPCIONAL) GENERAR TU EVIDENCIA COMPLETA SOLO CUANDO HAY CAMBIO
        evidence_name = f"{HOST}_evidence_{ts}.txt"
        evidence_path = os.path.join(device_folder, evidence_name)
        with open(evidence_path, "w", encoding="utf-8") as f:
            f.write(f"IPAM evidence generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("="*60 + "\n\n")
            for cmd in COMMANDS:
                f.write(f">>> {cmd}\n")
                try:
                    out = conn.send_command(cmd, delay_factor=1)
                except Exception as exc:
                    out = f"ERROR ejecutando comando: {exc}"
                f.write(out + "\n\n")
            for target in PING_TARGETS:
                cmd = f"ping {target}"
                f.write(f">>> {cmd}\n")
                try:
                    out = conn.send_command(cmd, delay_factor=1)
                except Exception as exc:
                    out = f"ERROR ejecutando ping: {exc}"
                f.write(out + "\n\n")

        # 4) INFO DE CONSOLA (igual que antes)
        raw_interfaces = conn.send_command("show ip interface brief")
        rows = []
        for line in raw_interfaces.splitlines():
            if line.strip() and not line.startswith("Interface"):
                parts = line.split()
                if len(parts) >= 2:
                    iface = parts[0]
                    ip = parts[1] if parts[1].lower() != "unassigned" else ""
                    status = " ".join(parts[4:6]) if len(parts) >= 6 else ""
                    rows.append([iface, ip, status])

        raw_neighbors = conn.send_command("show ip ospf neighbor")
        neigh_rows = []
        for line in raw_neighbors.splitlines():
            if line.strip() and line[0].isdigit():
                parts = line.split()
                if len(parts) >= 6:
                    neigh_id = parts[0]
                    state = parts[2]
                    address = parts[4]
                    iface = parts[5]
                    neigh_rows.append([neigh_id, state, address, iface])

        conn.disconnect()

        print("\n✅ Cambios detectados en running-config. Se guardó backup y evidencia.")
        print(f"- Config (normalizada): {cfg_path}")
        print(f"- Evidencia: {evidence_path}")

        # 5) SUBIR A GITHUB SOLO CUANDO HAY CAMBIO
        _git_push_if_needed(f"Backup {HOST} {ts}")

    else:
        conn.disconnect()
        print("\n⚙️ Sin cambios en running-config: no se guardó nada y no hubo push.")

if __name__ == "__main__":
    # loop cada 5s, pero ahora NO creará archivos a menos que cambie la config
    while True:
        run_once()
        time.sleep(5)
