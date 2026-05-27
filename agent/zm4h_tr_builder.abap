REPORT zm4h_tr_builder.
* Migrate4HANA in-system transport builder (v7). Uses abapGit's ZCL_ABAPGIT_DEFAULT_TRANSPORT to
* set a default transport request so non-dialog object recording succeeds (the step RS_CORR_INSERT
* cancelled on without a default). Creates request+task, sets default transport=task, creates a
* harmless program + records it, resets default, releases the request (exports cofile/datafile).
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
      lv_korr  TYPE trkorr,
      lv_order TYPE trkorr,
      lt_src   TYPE STANDARD TABLE OF string,
      ls_ret   TYPE bapiret2,
      lx       TYPE REF TO cx_root.

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
    OTHERS            = 1.
lv_req = ls_reqh-trkorr.
READ TABLE lt_taskh INTO ls_taskh INDEX 1.
lv_task = ls_taskh-trkorr.
lv_line = |step1_create subrc={ sy-subrc } req={ lv_req } task={ lv_task }|.
addln lv_line.

* 2) set abapGit default transport = our task (so non-dialog recording uses it, no prompt/cancel)
TRY.
    zcl_abapgit_default_transport=>get_instance( )->set( lv_task ).
    lv_line = |step2_set_default_transport ok|.
  CATCH cx_root INTO lx.
    lv_line = |step2_set_default_transport ERR { lx->get_text( ) }|.
ENDTRY.
addln lv_line.

* 3) create the harmless program + register/record it (default transport now resolves)
APPEND 'REPORT zm4h_tprobe01.' TO lt_src.
APPEND `WRITE / 'M4H transport probe - harmless throwaway'.` TO lt_src.
INSERT REPORT 'ZM4H_TPROBE01' FROM lt_src.
lv_line = |step3_insert_report subrc={ sy-subrc }|.
addln lv_line.
CALL FUNCTION 'RS_CORR_INSERT'
  EXPORTING
    object          = 'ZM4H_TPROBE01'
    object_class    = 'ABAP'
    devclass        = 'Z001'
    mode            = 'I'
    global_lock     = 'X'
    korrnum         = lv_task
    program         = 'ZM4H_TPROBE01'
    master_language = sy-langu
    suppress_dialog = 'X'
  IMPORTING
    korrnum         = lv_korr
    ordernum        = lv_order
  EXCEPTIONS
    cancelled           = 1
    permission_failure  = 2
    unknown_objectclass = 3
    OTHERS              = 4.
lv_line = |step3b_rs_corr_insert subrc={ sy-subrc } korr={ lv_korr } order={ lv_order }|.
addln lv_line.

* 4) reset the default transport
TRY.
    zcl_abapgit_default_transport=>get_instance( )->reset( ).
  CATCH cx_root INTO lx.
ENDTRY.

* 5) release the request (complete = release task + request -> exports cofile/datafile)
CALL FUNCTION 'BAPI_CTREQUEST_RELEASE'
  EXPORTING
    requestid = lv_req
    complete  = 'X'
  IMPORTING
    return    = ls_ret.
lv_line = |step5_release type={ ls_ret-type } msg={ ls_ret-message }|.
addln lv_line.

lv_line = |TRKORR={ lv_req }|.
addln lv_line.
addln 'DONE'.

OPEN DATASET lv_file FOR OUTPUT IN TEXT MODE ENCODING DEFAULT.
IF sy-subrc = 0.
  TRANSFER lv_out TO lv_file.
  CLOSE DATASET lv_file.
ENDIF.
