
var g_name= '';
var g_type = '';
var g_search = '';
var max_datapoints = 120;

//var colours = ['#e0b296', '#78cdc8', '#2e2e9e'];
var colours = [ '#A2383B', '#c78200', '#2f6473'];

function get_period(){

    var period = 'day';
    var interval = 60 * 20;
    if ($("#day").is(":checked")) { console.log("aoeu'"); period = 'day'; interval = 60 * 30 ; } // hours
    else if ($("#hour").is(":checked")) {period = 'hour'; interval = 60 } // minutes
    else if ($("#hour4").is(":checked")) {period = '4hour'; interval = 60 * 4 } // 4 minutes
    else if ($("#hour12").is(":checked")) {period = '12hour'; interval = 60 * 15 }
    else if ($("#week").is(":checked")) {period = 'week'; interval = 60 * 15 * 7 } //  6 hours
    else if ($("#month").is(":checked")) {period = 'month'; interval = 60 * 60 * 31 } // day
    return [period, interval];
    }

function load_composite_graph(canvas_id, types, title)
{
    var x= get_period();
    var period = x[0];
    var interval = x[1];
    res_data = [];
    var options= {
        animation : false,
        responsive: false,
        highLight: true,
        annotateLabel: "<%=v2+': '+v1+' '+v3%>",
        annotateDisplay: true,
        graphTitle : title ,
        legend: true,
        datasetFill : true,
    };

    var labels = null;
    for (var i=0 ; i < types.length; i++) {
        $.ajax({
                url: script_root + '/data/',
                type: 'POST',
                data:  JSON.stringify({'type': types[i], 'period': period, 'interval': interval}),
                cache: false,
                async: false,
                contentType: "application/json;charset=UTF-8",
        }).done(function(data) {
            var res = JSON.parse(data);
            if (res.labels.length > 0 && res.data.length > 0) {
                res_data[i] = {
                type: "line",
                    fillColor: colours[i],
                    strokeColor: colours[i],
                    data: res.data,
                    title: types[i]
                }
            }
            console.log(res);
            if (labels === null) {labels = res.labels;}
        });
    }

    var data = {
        labels: labels,
        datasets: res_data
    };
    console.log(data);
    new Chart(document.getElementById(canvas_id).getContext("2d")).StackedBar(data, options);
    return false;
}

function load_graph(canvas_id, type)
{
    var x= get_period();
    var period = x[0];
    var interval = x[1];
    $.ajax({
        url: script_root + '/data/',
        type: 'POST',
        data:  JSON.stringify({'type': type,  'period': period, 'interval': interval}),
        cache: false,
        contentType: "application/json;charset=UTF-8",
    }).done(function(data) {
        var res = JSON.parse(data);
        console.log(res.title);
        var options= {
            graphTitle: res.title,
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
            fillColor: colours[0],
            strokeColor: colours[0],
            data: res.data,
            title: type
        }]
        }
         new Chart(document.getElementById(canvas_id).getContext("2d")).StackedBar(data, options);
    });
    return false;
}

function load_all_graphs()
{
    var types = ["temperature", 'humidity', 'pressure', 'oxidising', 'reducing', 'nh3', "lux" , "proximity" ];
//    , "pm1" , "pm25", "pm10", "noise_low", "noise_mid", "noise_high"];
    for (let i = 0; i < types.length; i++) {
        load_graph('canvas_' + types[i], types[i]);
    }
    var composite_type = [ "pm10", "pm25", "pm1"];
    load_composite_graph('canvas_pm', composite_type, "Particles")
    var composite_type = [ "noise_high", "noise_mid", "noise_low"];
    load_composite_graph('canvas_noise', composite_type, "Noise")
}

function round(nr, dig)
{
    exp = 10 ** dig;
    return Math.round((nr+ Number.EPSILON) * exp)/exp;
}


function load_currents()
{
 $.ajax({
        url: script_root + '/latest/',
        type: 'POST',
        cache: false,
        contentType: "application/json;charset=UTF-8",

    }).done(function(data) {
        var res = JSON.parse(data);
        $("#current_temperature").text(round(res['data']['temperature'],1));
        $("#current_humidity").text(round(res['data']['humidity'],1));
        $("#current_pressure").text(round(res['data']['pressure'],0));
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
