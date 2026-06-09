import csv
import random
from datetime import datetime, timedelta
from faker import Faker

fake = Faker()

def get_legacy_sap_date(start_year=1996, end_year=2015):
    """Generates an SAP-formatted date string (YYYYMMDD) over a legacy range."""
    start_date = datetime(start_year, 1, 1)
    end_date = datetime(end_year, 12, 31)
    random_date = start_date + timedelta(days=random.randint(0, (end_date - start_date).days))
    return random_date.strftime("%Y%m%d")

def corrupt_text(text):
    """Deliberately injects real-world formatting anomalies into strings."""
    corruption_type = random.choice(['lowercase', 'uppercase', 'trailing', 'special', 'clean'])
    if corruption_type == 'lowercase':
        return text.lower()
    elif corruption_type == 'uppercase':
        return text.upper()
    elif corruption_type == 'trailing':
        return f"   {text}   "
    elif corruption_type == 'special':
        return f"{text} #GBLTD*"
    return text

def generate_dirty_customers(count=1000):
    customers = []
    for i in range(1, count + 1):
        kunnr = f"LEG_{i:06d}"
        name1 = corrupt_text(fake.company())
        name2 = corrupt_text(fake.name()) if random.random() > 0.3 else ""
        
        # Simulating inconsistent phone format anomalies
        telf1 = fake.phone_number() if random.random() > 0.1 else "000-0000" 
        stceg = f"US{random.randint(100000000, 999999999)}" if random.random() > 0.2 else ""
        erdat = get_legacy_sap_date()
        
        # Dynamic Custom Fields (Testing Foundation F3/F5)
        zz_legacy_id = f"SYS-OLD-{random.randint(10000, 99999)}"
        
        customers.append({
            'KUNNR': kunnr, 'NAME1': name1[:35], 'NAME2': name2[:35],
            'ORT01': fake.city()[:35], 'PSTLZ': fake.zipcode()[:10],
            'LAND1': 'US', 'TELF1': telf1[:16], 'STCEG': stceg[:20],
            'ERDAT': erdat, 'ZZ_LEGACY_ID': zz_legacy_id
        })
    return customers

def generate_dirty_materials(count=1000):
    materials = []
    mat_types = ['ROH', 'HALB', 'FERT', 'ZLEG'] # ZLEG simulates a legacy custom material type
    for i in range(1, count + 1):
        matnr = f"MAT_LEG_{i:05d}"
        maktx = corrupt_text(fake.catch_phrase())
        meins = random.choice(['PC', 'KG', 'L', 'BOX', '   ']) # Empty/invalid unit spaces
        brgew = round(random.uniform(0.1, 500.0), 3) if random.random() > 0.1 else 0.0
        erdat = get_legacy_sap_date()
        
        materials.append({
            'MATNR': matnr, 'MTART': random.choice(mat_types),
            'MBRSH': 'M', 'MEINS': meins, 'MAKTX': maktx[:40],
            'BRGEW': brgew, 'GEWEI': 'KG', 'ERDAT': erdat
        })
    return materials

if __name__ == "__main__":
    print("Generating 5,000 legacy customer records...")
    cust_data = generate_dirty_customers(5000)
    with open('dirty_kna1.csv', 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=cust_data[0].keys())
        writer.writeheader()
        writer.writerows(cust_data)
        
    print("Generating 5,000 legacy material records...")
    mat_data = generate_dirty_materials(5000)
    with open('dirty_mara.csv', 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=mat_data[0].keys())
        writer.writeheader()
        writer.writerows(mat_data)
    print("Success. Legacy files generated.")