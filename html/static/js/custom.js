"use strict";

var colours = [ '#A2383B', '#c78200', '#2f6473'];

function get_period()
{
    var period = 'day';
    var interval = 60 * 20;
    if ($("#day").is(":checked")) { period = 'day'; interval = 60 * 30 ; } // hours
    else if ($("#hour").is(":checked")) {period = 'hour'; interval = 60 } // minutes
    else if ($("#hour4").is(":checked")) {period = '4hour'; interval = 60 * 4 } // 4 minutes
    else if ($("#hour12").is(":checked")) {period = '12hour'; interval = 60 * 15 }
    else if ($("#week").is(":checked")) {period = 'week'; interval = 60 * 15 * 7 } //  6 hours
    else if ($("#month").is(":checked")) {period = 'month'; interval = 60 * 60 * 31 } // day
    else if ($("#custom").is(":checked")) {
        period = 'custom';
        var from = $("#from_date").val();
        var to = $("#to_date").val();
        return [period, [from, to] ]
    }

    return [period, interval];
}

function load_composite_graph(canvas_id, types, title)
{
    var x = get_period();
    var period = x[0];
    var interval = x[1];
    var res_data = [];
    var options= {
        graphTitleFontSize: 16,
        canvasBorders: true,
        canvasBordersWidth: 1,
        barDatasetSpacing: 0,
        barValueSpacing:0,
        animation : false,
        responsive: true,
        highLight: true,
        annotateLabel: "<%=v2+': '+v1+' '+v3%>",
        annotateDisplay: true,
        graphTitle : title ,
        legend: true,
        datasetFill : true,
        showXLabels: false,
        yAxisUnitFontSize: 16,
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
            var interval_size = calculate_yaxis(res.data) ;
            if (res.labels.length > 0 && res.data.length > 0) {
                res_data[i] = {
                    type: "line",
                    fillColor: colours[i],
                    strokeColor: colours[i],
                    data: res.data,
                    title: types[i].replace(/_/g, " ")
                };
                options['yAxisUnit'] = res.unit;
                options['yAxisMinimumInterval'] = interval_size;
            }
//            console.log(res);
            if (labels === null) {labels = res.labels;}
        });
    }

    var data = {
        labels: labels,
        datasets: res_data
    };
//    console.log(data);
    new Chart(document.getElementById(canvas_id).getContext("2d")).StackedBar(data, options);
    return false;
}

function calculate_yaxis(data)
{
    var val = Math.abs(Math.max(...data) - Math.min(...data));
//    var interval_size = 0.01;
//    if (val > 0.1) { interval_size = .025;}
//    if (val > 1) { interval_size = .25;}
//    if (val > 10) { interval_size = 1;}
//    if (val > 100) { interval_size = 10;}
//    if (val > 1000) { interval_size = 100;}
//    if (val > 10000) { interval_size = 1000;}
//    if (val > 100000) { interval_size = 10000;}
    var interval_size = val / 10;
    var lg = Math.floor(Math.log(interval_size) / Math.log(10) + 1);
//    console.log(lg, val, (Math.max(...data)- Math.min(...data))/10);
    if (lg < 0) {
        interval_size = round(interval_size, -lg +1 );
    } else {
        interval_size = round(interval_size, 1);
    }
//    if (val < 1 )  {interval_size = round(interval_size, 2);}
//    else if (val < 10 )  {interval_size = round(interval_size, 1);}
//    else {interval_size = round(interval_size,0 );}
//    if (val < 0.1) { interval_size = val;}
//    console.log(val, interval_size);
    return interval_size;
}

function load_graph(canvas_id, type)
{
    var x= get_period();
    var period = x[0];
    var interval = x[1];
    $.ajax({
        url: script_root + '/data/',
        type: 'POST',
        data:  JSON.stringify({'type': type, 'period': period, 'interval': interval}),
        cache: false,
        contentType: "application/json;charset=UTF-8",
    }).done(function(data) {
        var res = JSON.parse(data);
        var interval_size = calculate_yaxis(res.data) ;
//        console.log(interval_size);
        var options= {
            graphTitle: res.title,
            graphTitleFontSize: 16,
            canvasBorders: true,
            canvasBordersWidth: 1,
            barDatasetSpacing: 0,
            barValueSpacing:0,
            animation : false,
            responsive: true,
            highLight: true,
            annotateLabel: "<%=v2+': '+v1+' '+v3%>",
            annotateDisplay: true,
            yAxisMinimumInterval:interval_size,
            showXLabels: false,
            yAxisUnit: res.unit,
            yAxisUnitFontSize: 16,
        };
        if (res.labels.length == 0 || res.data.length == 0) { return }
        var data = {
            labels: res.labels,
            datasets: [{
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

var simple_types = ["temperature", 'humidity', 'pressure', 'oxidising', 'reducing', 'nh3', "lux" , "proximity"
                , "pm1" , "pm25", "pm10", "noise_low", "noise_mid", "noise_high"];

var composite_types = ["noise", "particles"];
var all_types = simple_types.concat(composite_types);

function update_session()
{
    var types = all_types;
    var selected = {}
//    console.log(all_types);
    for (let i = 0; i < types.length; i++) {
//        console.log("#setting_" + types[i]);
        if ($("#setting_" + types[i])[0].checked) {
            selected[types[i]] = 1;
        } else {
            selected[types[i]] = 0;
        }
    }
//    console.log(selected)
    $.ajax({
        url: script_root + '/update_session/',
        type: 'POST',
        cache: false,
        contentType: "application/json;charset=UTF-8",
        data : JSON.stringify({'selected': selected}),
        async : true,
    }).done(function(data) {
    });
}

function load_all_graphs()
{
    var types = simple_types;
    for (let i = 0; i < types.length; i++) {
        if ($("#setting_" + types[i])[0].checked) {
//            console.log(types[i]);
            $('#canvas_div_'+ types[i]).show();
            load_graph('canvas_' + types[i], types[i]);
        } else {
            $('#canvas_div_'+ types[i]).hide();
        }
    }
    var composite_type = [ "pm10", "pm25", "pm1"];
    if ($('#setting_particles')[0].checked) {
            $("#canvas_particles").show();
            load_composite_graph('canvas_particles', composite_type, "Particles")
        } else {
        $("#canvas_particles").hide();
    }
    var composite_type = [ "noise_high", "noise_mid", "noise_low"];
    if ($('#setting_noise')[0].checked) {
        $("#canvas_noise").show();
            load_composite_graph('canvas_noise', composite_type, "Noise")
        } else {
            $("#canvas_noise").hide();
    }
}

function round(nr, dig)
{
    var exp = 10 ** dig; return Math.round((nr+ Number.EPSILON) * exp)/exp;
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
        var temp_desc = res['description']['temperature']
        var hum_desc = res['description']['humidity']
        var press_desc = res['description']['pressure']
//        console.log(img_path, hum_desc, temp_desc, res)
        $("#current_temperature").text(round(res['data']['temperature'],1) + res['units']['temperature']);
        $("#current_humidity").text(round(res['data']['humidity'],1) + res['units']['humidity']);
        $("#current_pressure").text(round(res['data']['pressure'],0) + ' ' +res['units']['pressure']);
//       console.log(img_path + "/humidity_" + hum_desc + '.png')
        $("#humidity_icon").attr("src", img_path + "/humidity-" + hum_desc + '.png')
        $("#temperature_icon").attr("src", img_path + "/temperature-" + temp_desc + '.png')
        $("#pressure_icon").attr("src", img_path + "/pressure-" + press_desc + '.png')
    });
}

function load_sun_times()
{
    $.ajax({
        url: script_root + '/sun/',
        type: 'POST',
        cache: false,
        contentType: "application/json;charset=UTF-8",
    }).done(function(data) {
        var res = JSON.parse(data);
//        console.log(res);
        $("#next_sunrise").text(res.sun_up);
        $("#next_sunset").text(res.sun_down);
    });
}


function load_details(type)
{
var avg = 0;
var mx = 0;
var mn = 0;
var std = 0
var chg = '';
var trend = null;
var period = get_period()[0]

 $.ajax({
        url: script_root + '/details/',
        type: 'POST',
        cache: false,
        async: false,
        data:  JSON.stringify({'type': type, 'period': period, 'interval': 1}),
        contentType: "application/json;charset=UTF-8",

    }).done(function(data) {
        var res = JSON.parse(data);
//        console.log(res.data.avg);
        avg = round(res.data.avg, 2);
        mn = round(res.data.min, 2);
        mx = round(res.data.max, 2);
        std = round(res.data.std, 2);
        chg = round(res.data.change_per_hour, 2);
        trend = res.data.trend;
    });
        return "Avg: " + avg + "<br>Min: " + mn + "<br>Max: " + mx + "<br>Std Dev: " + std  + "<br><br>Change: " + chg + " " + trend;
}

function calculate_height()
{
    var nb_height = $("#navbar").height();
    var b_height = $("body").height();
    var m_height = $("#maindiv").height();
    var w_height = window.innerHeight;
    var res_height = Math.floor(w_height-nb_height) - 18;
    console.log(w_height, nb_height, res_height, b_height, m_height);
    $('#maindiv').height(res_height);
}

$( document ).ready(function() {
    var display = false;
    var add_items_lock = 0
    $('.dropdown-toggle').dropdown()
    $('[data-toggle="popover"]').popover();
    $('body').css('background-image', 'url("' + script_root + '/static/img/background.gif")');
    $('body').css('background-size', 'contain');

    $("[name^='timeperiod").click(function(event) {
        if ($(this).attr('id') !='custom') {
        $("#time_selector").hide();
        load_all_graphs();
        }
    });
    $("#custom").click(function() {  $('#timepicker').toggleClass('d-none');});
    $("#submit_custom").click(function() {
//        console.log($("#custom").prop("checked"));
        $("#custom").prop("checked", true);
//        console.log($("#custom").prop("checked"));
        load_all_graphs();
    });
    load_all_graphs();
    load_currents();

    $('[name="selected"').change(function(event) {
        update_session();
    });
    $("#pressure_details").click(function(event) {
        $("#pressure_details").popover( {trigger: 'manual', content: function() {return load_details('pressure');}, html: true}).popover("show");
        setTimeout(function(){ $("#pressure_details").popover("hide");}, 5000)
    });
    $("#temperature_details").click(function(event) {
        $("#temperature_details").popover( {trigger: 'manual', content: function() {return load_details('temperature');}, html: true}).popover("show");
        setTimeout(function(){ $("#temperature_details").popover("hide");}, 5000)
    });
    $("#humidity_details").click(function(event) {
        $("#humidity_details").popover( {trigger: 'manual', content:function() {return load_details('humidity');}, html: true}).popover("show");
        setTimeout(function(){ $("#humidity_details").popover("hide");}, 5000)
    });

    load_sun_times();
    setInterval(load_currents, 5000);
    setInterval(load_sun_times, 1000 * 60 * 60);
    calculate_height();
});

