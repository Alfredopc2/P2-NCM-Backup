# ipam_full_evidence.py  (versión mínima para cumplir P2-NCM-Backup)
from netmiko import ConnectHandler
from tabulate import tabulate
import time, os, difflib, subprocess
from datetime import datetime

HOST = "192.168.0.161"
USER = "admin"
PASSWORD = "alfredo123"
PORT = 22

# comandos base (LOS MISMOS)
COMMANDS = [
    "show ip interface brief",
    "show ip route",
    "show ip ospf neighbor",
    "show ip ospf"
]

PING_TARGETS = ["2.2.2.2", "3.3.3.3"]

BACKUP_ROOT = "backups"  # NUEVO: raíz de respaldos por dispositivo
os.makedirs(BACKUP_ROOT, exist_ok=True)

def _git_push_if_needed(msg):
    try:
        subprocess.run(["git", "add", "."], check=False)
        # commit solo si hay cambios en staging
        subprocess.run(["git", "commit", "-m", msg], check=False)
        subprocess.run(["git", "push"], check=False)
    except Exception:
        # si no hay git o credenciales, no rompemos el backup
        pass

def _last_backup_path(folder):
    if not os.path.isdir(folder):
        return None
    txts = sorted([f for f in os.listdir(folder) if f.endswith(".txt") and f != "current.txt"])
    return os.path.join(folder, txts[-1]) if txts else None

def _different_files(a, b):
    if not b or not os.path.exists(b):
        return True
    with open(a, encoding="utf-8", errors="ignore") as fa, open(b, encoding="utf-8", errors="ignore") as fb:
        diff = list(difflib.unified_diff(fa.readlines(), fb.readlines()))
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

    # ===== Generar salida como antes (tu evidencia completa) =====
    timestamp_humano = time.strftime("%Y-%m-%d %H:%M:%S")
    # NUEVO: carpeta por dispositivo
    device_folder = os.path.join(BACKUP_ROOT, HOST)
    os.makedirs(device_folder, exist_ok=True)

    # archivo temporal "current" para comparar
    temp_path = os.path.join(device_folder, "current.txt")
    with open(temp_path, "w", encoding="utf-8") as f:
        f.write(f"IPAM evidence generated: {timestamp_humano}\n")
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

    # ===== PARSEOS PARA CONSOLA (igual que tu script) =====
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

    print("\n==== INTERFACES (R1) ====")
    print(tabulate(rows, headers=["Interface", "IP", "Status"], tablefmt="pretty"))

    print("\n==== OSPF NEIGHBORS (R1) ====")
    print(tabulate(neigh_rows, headers=["Neighbor ID","State","Address","Interface"], tablefmt="pretty"))

    # ===== Comparar con el último backup y guardar SOLO si cambió =====
    last = _last_backup_path(device_folder)
    if _different_files(temp_path, last):
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        final_name = f"{HOST}_backup_{ts}.txt"     # nombre con fecha/hora
        final_path = os.path.join(device_folder, final_name)
        os.replace(temp_path, final_path)
        print(f"\n Cambios detectados. Backup guardado en {final_path}")

        # push automático a GitHub (silencioso si no hay git)
        _git_push_if_needed(f"Backup {HOST} {ts}")
    else:
        os.remove(temp_path)
        print("\n Sin cambios: no se generó un nuevo backup.")

    print(f"\nEvidencia/listado en: {device_folder}")

if __name__ == "__main__":
    # ejecutar cada 5 segundos (requisito)
    while True:
        run_once()
        print("\nEsperando 5 segundos para el siguiente ciclo...\n")
        time.sleep(5)
