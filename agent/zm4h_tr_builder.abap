REPORT zm4h_tr_builder.
* Migrate4HANA in-system transport builder (v6). Creates a workbench request + task, creates a
* harmless program, writes its TADIR entry into transportable package Z001 + records it to the
* TASK via TR_TADIR_INTERFACE (non-dialog), then releases the request (exports cofile/datafile).
DATA: lv_file  TYPE string VALUE '/usr/sap/trans/tmp/m4h_tr_result.txt',
      lv_out   TYPE string,
      lv_line  TYPE string,
      lt_users TYPE scts_users,
      ls_user  TYPE scts_user,
      ls_reqh  TYPE trwbo_request_header,
      lt_taskh TYPE trwbo_request_headers,
      ls_taskh TYPE trwbo_request_header,
      lv_req   TYPE trkorr,
      lv_task  TYPE trkorr,
      lt_src   TYPE STANDARD TABLE OF string,
      ls_ret   TYPE bapiret2.

DEFINE addln.
  CONCATENATE lv_out &1 cl_abap_char_utilities=>newline INTO lv_out.
END-OF-DEFINITION.

* 1) create workbench request + a development task for the current user
ls_user-user = sy-uname.
ls_user-type = 'S'.
APPEND ls_user TO lt_users.
CALL FUNCTION 'TR_INSERT_REQUEST_WITH_TASKS'
  EXPORTING
    iv_type           = 'K'
    iv_text           = 'M4H transport-chain probe (harmless)'
    iv_owner          = sy-uname
    it_users          = lt_users
  IMPORTING
    es_request_header = ls_reqh
    et_task_headers   = lt_taskh
  EXCEPTIONS
    insert_failed     = 1
    enqueue_failed    = 2
    OTHERS            = 3.
lv_req = ls_reqh-trkorr.
READ TABLE lt_taskh INTO ls_taskh INDEX 1.
lv_task = ls_taskh-trkorr.
lv_line = |step1_create subrc={ sy-subrc } req={ lv_req } task={ lv_task }|.
addln lv_line.

* 2) create the harmless program source
APPEND 'REPORT zm4h_tprobe01.' TO lt_src.
APPEND `WRITE / 'M4H transport probe - harmless throwaway'.` TO lt_src.
INSERT REPORT 'ZM4H_TPROBE01' FROM lt_src.
lv_line = |step2_insert_report subrc={ sy-subrc }|.
addln lv_line.

* 3) write TADIR (package Z001) + record object to the TASK (non-dialog, TEST_MODUS off)
CALL FUNCTION 'TR_TADIR_INTERFACE'
  EXPORTING
    wi_tadir_pgmid      = 'R3TR'
    wi_tadir_object     = 'PROG'
    wi_tadir_obj_name   = 'ZM4H_TPROBE01'
    wi_tadir_devclass   = 'Z001'
    wi_tadir_korrnum    = lv_task
    wi_tadir_author     = sy-uname
    wi_tadir_masterlang = sy-langu
    wi_test_modus       = ' '
  EXCEPTIONS
    OTHERS              = 1.
lv_line = |step3_tadir subrc={ sy-subrc }|.
addln lv_line.

* 4) release the request (complete = release task + request -> exports cofile/datafile)
CALL FUNCTION 'BAPI_CTREQUEST_RELEASE'
  EXPORTING
    requestid = lv_req
    complete  = 'X'
  IMPORTING
    return    = ls_ret.
lv_line = |step4_release type={ ls_ret-type } msg={ ls_ret-message }|.
addln lv_line.

lv_line = |TRKORR={ lv_req }|.
addln lv_line.
addln 'DONE'.

OPEN DATASET lv_file FOR OUTPUT IN TEXT MODE ENCODING DEFAULT.
IF sy-subrc = 0.
  TRANSFER lv_out TO lv_file.
  CLOSE DATASET lv_file.
ENDIF.
