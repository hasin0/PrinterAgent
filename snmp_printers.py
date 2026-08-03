from toner_monitor import check_toner_sync

ips = [
    "172.16.16.31",
    "172.16.16.40",
    "172.16.16.33",
    "172.16.18.88",
    "172.16.18.116",
    "172.16.16.42",
    "172.16.16.47",
    "172.16.16.46",
    "172.16.16.48",
    "172.16.2.190",
    "172.16.14.165",
    "172.20.231.74",
    "172.20.229.92",
    "172.16.18.137",
    "172.16.18.211"
]

for ip in ips:
    print("=" * 60)
    print("Checking:", ip)

    try:
        result = check_toner_sync(ip)

        print(
            "Online:",
            result.get("online")
        )

        print(
            "Printer:",
            result.get("printer_name")
        )

    except Exception as e:
        print("Error:", e)