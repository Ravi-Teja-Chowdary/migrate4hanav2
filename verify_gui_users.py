from pyrfc import Connection
import os
os.environ.setdefault("SAPNWRFC_HOME", os.path.join(os.path.dirname(os.path.abspath(__file__)), "sapnwrfc"))
HOST = "vhcals4hci.dummy.nodomain"
for u in ["SAP*", "DDIC"]:
    try:
        c = Connection(ashost=HOST, sysnr="00", client="100", user=u, passwd="Parupallitejaajay#92", lang="EN")
        sid = c.call("RFC_SYSTEM_INFO")["RFCSI_EXPORT"]["RFCSYSID"]
        print(u, "+ master password (#92) -> LOGIN OK (" + sid + ") -- can use SAP GUI")
        c.close()
    except Exception as e:
        print(u, "+ master password (#92) -> FAIL:", getattr(e, "key", type(e).__name__))
