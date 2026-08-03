import asyncio

from pysnmp.hlapi.v3arch.asyncio import (
    SnmpEngine,
    CommunityData,
    ContextData,
    ObjectType,
    ObjectIdentity,
    UdpTransportTarget,
    next_cmd,
)


async def snmp_walk_limited(ip, base_oid, community="public", max_rows=30):
    results = {}

    transport = await UdpTransportTarget.create(
        (ip, 161),
        timeout=2,
        retries=0
    )

    current_oid = ObjectIdentity(base_oid)

    for _ in range(max_rows):
        error_indication, error_status, error_index, var_binds = await next_cmd(
            SnmpEngine(),
            CommunityData(community, mpModel=1),
            transport,
            ContextData(),
            ObjectType(current_oid),
            lexicographicMode=False
        )

        if error_indication:
            print("SNMP Error:", error_indication)
            break

        if error_status:
            print("SNMP Status Error:", error_status.prettyPrint())
            break

        if not var_binds:
            break

        for var_bind in var_binds:
            oid_text = str(var_bind[0])
            value_text = str(var_bind[1])

            if not oid_text.startswith(base_oid):
                return results

            results[oid_text] = value_text
            current_oid = ObjectIdentity(oid_text)

    return results


async def main():
    printer_ip = "172.20.231.74"

    description_oid = "1.3.6.1.2.1.43.11.1.1.6.1"
    max_capacity_oid = "1.3.6.1.2.1.43.11.1.1.8.1"
    current_level_oid = "1.3.6.1.2.1.43.11.1.1.9.1"

    print(f"Checking toner levels for printer: {printer_ip}")
    print("=" * 60)

    print("Reading supply descriptions...")
    descriptions = await snmp_walk_limited(printer_ip, description_oid)

    print("Reading max capacities...")
    max_capacities = await snmp_walk_limited(printer_ip, max_capacity_oid)

    print("Reading current levels...")
    current_levels = await snmp_walk_limited(printer_ip, current_level_oid)

    print("\nSUPPLIES FOUND")
    print("=" * 60)

    if not descriptions:
        print("No toner/supply descriptions found.")
        return

    for desc_oid, description in descriptions.items():
        index = desc_oid.split(".")[-1]

        max_oid = f"{max_capacity_oid}.{index}"
        level_oid = f"{current_level_oid}.{index}"

        max_value = max_capacities.get(max_oid)
        current_value = current_levels.get(level_oid)

        print(f"\nItem: {description}")
        print(f"Index: {index}")
        print(f"Max Capacity: {max_value}")
        print(f"Current Level: {current_value}")

        try:
            max_int = int(max_value)
            current_int = int(current_value)

            if max_int > 0 and current_int >= 0:
                percent = round((current_int / max_int) * 100, 2)
                print(f"Percentage: {percent}%")
            else:
                print("Percentage: Unknown")

        except:
            print("Percentage: Unable to calculate")


if __name__ == "__main__":
    asyncio.run(main())