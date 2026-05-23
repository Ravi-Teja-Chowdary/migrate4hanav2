*&---------------------------------------------------------------------*
*& Report  Y00_TEST_CLASS                                              *
*&                                                                     *
*&---------------------------------------------------------------------*
*&                                                                     *
*&                                                                     *
*&---------------------------------------------------------------------*
REPORT Y00_TEST_CLASS.
TABLES SFLIGHT.
CLASS CL_FLIGHT DEFINITION.
  PUBLIC SECTION.
  METHODS : CONSTRUCTOR IMPORTING IM_CARRID LIKE SFLIGHT-CARRID IM_CONNID LIKE SFLIGHT-CONNID IM_FLDATE LIKE SFLIGHT-FLDATE , SET_DATA IMPORTING IM_CARRID LIKE SFLIGHT-CARRID IM_CONNID LIKE SFLIGHT-CONNID IM_FLDATE LIKE SFLIGHT-FLDATE , GET_DATA EXPORTING EX_CARRID LIKE SFLIGHT-CARRID EX_CONNID LIKE SFLIGHT-CONNID EX_FLDATE LIKE SFLIGHT-FLDATE , WRITE_DATA.
  PRIVATE SECTION.
  DATA CARRID LIKE SFLIGHT-CARRID.
  DATA CONNID LIKE SFLIGHT-CONNID.
  DATA FLDATE LIKE SFLIGHT-FLDATE.
ENDCLASS.
CLASS CL_FLIGHT IMPLEMENTATION.
  METHOD CONSTRUCTOR.
    CARRID = IM_CARRID.
    CONNID = IM_CONNID.
    FLDATE = IM_FLDATE.
  ENDMETHOD.
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
  METHOD WRITE_DATA.
    WRITE /.
    'Fluggesellschaft:' ( 001 ) , 25 CARRID , / 'Flugverbindungsnummer:' ( 002 ) , 25 CONNID , / 'Flugdatum' ( 003 ) , 25 FLDATE , /.
  ENDMETHOD.
ENDCLASS.
DATA F1 TYPE REF TO CL_FLIGHT.
*** END OF DECLARATION ***
GET PARAMETER ID SFLIGHT FIELD .
CREATE OBJECT F1.
STOP.
END-OF-SELECTION.
CALL METHOD F1.