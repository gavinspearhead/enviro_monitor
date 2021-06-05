
var g_name= '';
var g_type = '';
var g_search = '';
var max_datapoints = 120;

function load_graph(canvas_id, type)
{
    var period = 'day';
    var interval = 60 * 60 * 10;
    if ($("#day").is(":checked")) {period = 'day'; interval = 60 * 60 ; } // hours
    else if ($("#hour").is(":checked")) {period = 'hour'; interval = 60 } // minutes
    else if ($("#hour4").is(":checked")) {period = '4hour'; interval = 60 * 4 } // 4 minutes
    else if ($("#hour12").is(":checked")) {period = '12hour'; interval = 60 * 12 } // 4 minutes
    else if ($("#week").is(":checked")) {period = 'week'; interval = 60 * 60 *  7 } // day
    else if ($("#month").is(":checked")) {period = 'month'; interval = 60 * 60 * 31 } // day
    console.log(period, interval);
    $.ajax({
        url: script_root + '/data/',
        type: 'POST',
        data:  JSON.stringify({'type': type,  'period': period, 'interval': interval}),
        cache: false,
        contentType: "application/json;charset=UTF-8",

    }).done(function(data) {
        var res = JSON.parse(data);
        var options= {
            animation : false,
            responsive: false,
            highLight: true,
            annotateLabel: "<%=v2+': '+v1+' '+v3%>",
            annotateDisplay: true,

        };
        if (res.labels.length == 0 || res.data.length == 0) {
        return
        }

        var data = {
        labels: res.labels,
        datasets: [
        {
            fillColor: "crimson",
            strokeColor: 'dark red',
            data: res.data,
            pointDotRadius: 1,
            pointColor: "orange",
            pointStrokeColor: "orange",
            title: type
        }]
        }
         new Chart(document.getElementById(canvas_id).getContext("2d")).Line(data, options);

    });
    return false;
}

function load_all_graphs()
{
    var types = ["temperature", 'humidity', 'pressure', 'oxidising', 'reducing', 'nh3', "lux" , "proximity" , "pm1" , "pm25", "pm10", "noise_low", "noise_mid", "noise_high"];
    for (let i = 0; i < types.length; i++) {
        load_graph('canvas_' + types[i], types[i],);
    }
}

function round(nr, dig)
{
    exp = 10 ** 2;
    return Math.round((nr+ Number.EPSILON) * exp)/exp;
}


function load_currents()
{
 $.ajax({
        url: script_root + '/latest/',
        type: 'POST',
//        data:  JSON.stringify({'type': type,  'period': period, 'interval': interval}),
        cache: false,
        contentType: "application/json;charset=UTF-8",

    }).done(function(data) {
        var res = JSON.parse(data);
//        console.log(res);
        $("#current_temperature").text(round(res['data']['temperature'],2))
        $("#current_humidity").text(round(res['data']['humidity'],2 ))
        $("#current_pressure").text(round(res['data']['pressure'],2 ))
    });
}


$( document ).ready(function() {
       
    add_items_lock = 0
    $('body').css('background-image', 'url("' + script_root + '/static/img/background.gif")');
    $('body').css('background-size', 'contain');

    $("[name^='timeperiod").click(function(event) {
        load_all_graphs();
    });
    load_all_graphs();
    load_currents();
    setInterval(load_currents, 5000);
});
