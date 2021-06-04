
var g_name= '';
var g_type = '';
var g_search = '';
var max_datapoints = 120;


function handle_request(name, type, search)
{
    console.log(name, type, search)
    g_name = name;
    g_type = type;
    g_search = search;
   var period = 'today';
    if ($("#daily").is(":checked")) {period = 'today';}
    else if ($("#hourly").is(":checked")) {period = 'hour';}
    else if ($("#yesterday").is(":checked")) {period = 'yesterday';}
    else if ($("#weekly").is(":checked")) {period = 'week';}
    else if ($("#monthly").is(":checked")) {period = 'month';}
    console.log(period);
    $.ajax({
        url: script_root + '/data/',
        type: 'POST',
        data:  JSON.stringify({'name': name, "type": type, 'period': period, 'search': search}),
        cache: false,
        contentType: "application/json;charset=UTF-8",

    }).done(function(data) {
        var res = JSON.parse(data);
        $('#itemstable').html(res.rhtml);
        document.title = ("Log Analyser - " + type + " " + name +  " " + period).replace("_", " ");
        $("#header").text((type + ": " + name).replace("_", " "));
    });
    return false;
}


function set_log_handlers()
{
    $("[id^='ssh_']").unbind('click');
    $("[id^='apache_']").unbind('click');
    $("[id^='ssh_']").click(function(event) {
        var type = "ssh";
        var name = $(this).attr("id").replace('ssh_', '');
        handle_request(name, type)
    });
    $("[id^='apache_']").click(function(event) {
        var type = "apache";
        var name = $(this).attr("id").replace('apache_', '');
        handle_request(name, type)
    });
    $("[name^='timeperiod").click(function(event) {
       handle_request(g_name, g_type, g_search);
    });
    $("#searchbutton").click(function(event) {
        handle_request(g_name, g_type, $("#searchbar").val())
    });

}

function load_graph(canvas_id, type)
{
    var period = 'day';
    var interval = 60 * 60 * 10;
    if ($("#day").is(":checked")) {period = 'day'; interval = 60 * 60 ;

    }
    else if ($("#hour").is(":checked")) {period = 'hour'; interval = 60 }
    else if ($("#week").is(":checked")) {period = 'week'; interval = 60* 60 *  7 }
    else if ($("#month").is(":checked")) {period = 'month'; interval = 60*60*31 }
    $.ajax({
        url: script_root + '/data/',
        type: 'POST',
        data:  JSON.stringify({'type': type,  'period': period, 'interval': interval}),
        cache: false,
        contentType: "application/json;charset=UTF-8",

    }).done(function(data) {
        var res = JSON.parse(data);
        console.log(res);
        var options= {
            animation : false

        };
        var data = {
        labels: res.labels,
        datasets: [
        {
            fillColor: "red",
            strokeColor: 'red',
            data: res.data,
            pointDotRadius: 0,
            title: type
        }]
        }

         new Chart(document.getElementById(canvas_id).getContext("2d")).Line(data, options);

    });
    return false;
}

function load_all_graphs()
{
    var types = ["temperature", 'humidity', 'pressure', 'oxidising', 'reducing', 'nh3', "lux" , "proximity" , "pm1" , "pm25", "pm10"];
    for (let i = 0; i < types.length; i++) {
//        console.log(types[i]);
        load_graph('canvas_' + types[i], types[i],);
    }
}
$( document ).ready(function() {
       
    add_items_lock = 0
    $('body').css('background-image', 'url("' + script_root + '/static/img/background.gif")');
    $('body').css('background-size', 'contain');

//    $('#itemstablediv').scrollTop(0);


//    set_log_handlers();
    $("[name^='timeperiod").click(function(event) {
        load_all_graphs()
    });
    load_all_graphs()
//    handle_request('users', "ssh", '');
});
