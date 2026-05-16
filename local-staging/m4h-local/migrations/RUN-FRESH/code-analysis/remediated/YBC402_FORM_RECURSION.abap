REPORT ybc402_form_recursion.
PARAMETERS :.
pa_num TYPE i.
DATA fakult TYPE f VALUE 1.
AT SELECTION-SCREEN.
IF pa_num > 170 OR pa_num < 1.
  MESSAGE e001 ( yse1 ).
ENDIF.
START-OF-SELECTION.
CHECK pa_num > 0.
PERFORM fakulty USING pa_num CHANGING fakult.
WRITE /.
pa_num NO-GAP , 'SCRUBBED_STRING' , ( 42 ) fakult.
FORM fakulty USING value ( p_pa_num ) TYPE i CHANGING p_fakult TYPE f.
  p_fakult = p_fakult * p_pa_num.
  p_pa_num = p_pa_num - 1.
  CHECK p_pa_num > 1.
  PERFORM fakulty USING p_pa_num CHANGING p_fakult.
ENDFORM.