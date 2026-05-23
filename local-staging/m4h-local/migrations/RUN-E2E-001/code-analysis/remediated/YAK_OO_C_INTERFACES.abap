*&---------------------------------------------------------------------*
*& Report  YAK_OO_C_INTERFACES                                         *
*&                                                                     *
*&---------------------------------------------------------------------*
REPORT YAK_OO_C_INTERFACES.
TABLES SFLIGHT.
* Interface definition
INTERFACE IF_WRITE.
  METHODS : WRITE_DATA.
ENDINTERFACE.
* Class definition
CLASS CL_FLIGHT DEFINITION.
  * Public section
  PUBLIC SECTION.
  INTERFACES : IF_WRITE.
  METHODS : SET_DATA IMPORTING IM_CARRID LIKE SFLIGHT-CARRID IM_CONNID LIKE SFLIGHT-CONNID IM_FLDATE LIKE SFLIGHT-FLDATE , GET_DATA EXPORTING EX_CARRID LIKE SFLIGHT-CARRID EX_CONNID LIKE SFLIGHT-CONNID EX_FLDATE LIKE SFLIGHT-FLDATE.
  *         write_data.
  * Private section.
  PRIVATE SECTION.
  DATA CARRID LIKE SFLIGHT-CARRID.
  DATA CONNID LIKE SFLIGHT-CONNID.
  DATA FLDATE LIKE SFLIGHT-FLDATE.
ENDCLASS.
* Class implementation
CLASS CL_FLIGHT IMPLEMENTATION.
  METHOD SET_DATA.
    CARRID = IM_CARRID.
    CONNID = IM_CONNID.
    FLDATE = IM_FLDATE.
  ENDMETHOD.
  METHOD GET_DATA.
    EX_CARRID = CARRID.
    EX_CONNID = CONNID.
    EX_FLDATE = FLDATE.
  ENDMETHOD.
  METHOD IF_WRITE~WRITE_DATA.
    WRITE /.
    'Fluggesellschaft:' ( 001 ) , 25 CARRID , / 'Flugverbindungsnummer:' ( 002 ) , 25 CONNID , / 'Flugdatum' ( 003 ) , 25 FLDATE , /.
  ENDMETHOD.
ENDCLASS.
DATA F1 TYPE REF TO CL_FLIGHT.
DATA F2 TYPE REF TO CL_FLIGHT.
DATA I1 TYPE REF TO IF_WRITE.
* START-OF-SELECTION
START-OF-SELECTION.
CREATE OBJECT F1.
CREATE OBJECT F2.
*   CALL METHOD f1->write_data.
CALL METHOD F2.
* GET sflight
GET PARAMETER ID SFLIGHT FIELD .
CALL METHOD F1.
STOP.
* END-OF-SELECTION
END-OF-SELECTION.
I1 = F1.
CALL METHOD I1.
I1 = F2.
CALL METHOD I1.
*   CALL METHOD i1->set_data EXPORTING im_carrid = 'LH'
*                                      im_connid = '400'
*                                      im_fldate = '19980926'.