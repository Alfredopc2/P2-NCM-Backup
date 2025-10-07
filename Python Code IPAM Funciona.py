# ipam_full_evidence.py
from netmiko import ConnectHandler
from tabulate import tabulate
import time

HOST = "192.168.0.161"
USER = "admin"
PASSWORD = "alfredo123"
PORT = 22

# comandos base
COMMANDS = [
    "show ip interface brief",
    "show ip route",
    "show ip ospf neighbor",
    "show ip ospf"
]

# pings a loopbacks de R2 y R3
PING_TARGETS = ["2.2.2.2", "3.3.3.3"]

OUTFILE = "ipam_evidence.txt"

def run():
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

    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(OUTFILE, "w", encoding="utf-8") as f:
        f.write(f"IPAM evidence generated: {timestamp}\n")
        f.write("="*60 + "\n\n")

        # ejecutar comandos show
        for cmd in COMMANDS:
            f.write(f">>> {cmd}\n")
            try:
                out = conn.send_command(cmd, delay_factor=1)
            except Exception as exc:
                out = f"ERROR ejecutando comando: {exc}"
            f.write(out + "\n\n")

        # ejecutar pings
        for target in PING_TARGETS:
            cmd = f"ping {target}"
            f.write(f">>> {cmd}\n")
            try:
                out = conn.send_command(cmd, delay_factor=1)
            except Exception as exc:
                out = f"ERROR ejecutando ping: {exc}"
            f.write(out + "\n\n")

    # parsear interfaces para consola
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

    # parse OSPF neighbors
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

    # imprimir resumen en consola
    print("\n==== INTERFACES (R1) ====")
    print(tabulate(rows, headers=["Interface", "IP", "Status"], tablefmt="pretty"))

    print("\n==== OSPF NEIGHBORS (R1) ====")
    print(tabulate(neigh_rows, headers=["Neighbor ID","State","Address","Interface"], tablefmt="pretty"))

    print(f"\nEvidencia completa guardada en ./{OUTFILE}")

if __name__ == "__main__":
    run()
