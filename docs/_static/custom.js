$(document).ready(function() {
    // hide argparse internal headers
    // waiting for https://github.com/ribozz/sphinx-argparse/issues/78
    jQuery("li a.reference.internal:contains('Positional Arguments')").parent().hide()
    jQuery("li a.reference.internal:contains('Named Arguments')").parent().hide()
});