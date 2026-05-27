REPORT zm4h_agent_probe.
* Migrate4HANA in-system agent probe - proves remote deploy + batch execution.
DATA lv_file TYPE string.
DATA lv_msg  TYPE string.
lv_file = '/usr/sap/trans/tmp/m4h_agent_probe.txt'.
CONCATENATE 'M4H agent OK uname=' sy-uname ' mandt=' sy-mandt
            ' date=' sy-datum ' time=' sy-uzeit INTO lv_msg.
OPEN DATASET lv_file FOR OUTPUT IN TEXT MODE ENCODING DEFAULT.
IF sy-subrc = 0.
  TRANSFER lv_msg TO lv_file.
  CLOSE DATASET lv_file.
ENDIF.
