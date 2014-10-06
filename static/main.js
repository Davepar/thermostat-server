// Get query string parameters (function from StackOverflow)
var qs = (function(a) {
    if (a == "") return {};
    var b = {};
    for (var i = 0; i < a.length; ++i)
    {
        var p=a[i].split('=');
        if (p.length != 2) continue;
        b[p[0]] = decodeURIComponent(p[1].replace(/\+/g, " "));
    }
    return b;
})(window.location.search.substr(1).split('&'));

var dweetId = qs['id'] || 'weatherstation';

var margin = {top: 20, right: 90, bottom: 30, left: 50},
    width = 960 - margin.left - margin.right,
    height = 500 - margin.top - margin.bottom;

var parseTime = d3.time.format.utc('%Y-%m-%d %H:%M:%S').parse;

var x = d3.time.scale()
    .range([0, width]);

var y = d3.scale.linear()
    .range([height, 0]);

var color = d3.scale.category10();

var xAxis = d3.svg.axis()
    .scale(x)
    .orient('bottom');

var yAxis = d3.svg.axis()
    .scale(y)
    .orient('left')
    .ticks(5);

var line = d3.svg.line()
    .interpolate('basis')
    .x(function(d) { return x(d.time); })
    .y(function(d) { return y(d.value); });

var svg = d3.select('#graph').append('svg')
    .attr('width', width + margin.left + margin.right)
    .attr('height', height + margin.top + margin.bottom)
  .append('g')
    .attr('transform', 'translate(' + margin.left + ',' + margin.top + ')');

// // Catch 404 error
// var title = 'Error: "' + json.because + '" for ID: ' + dweetId;
// if (json.with === 404) {
//   svg.append('text')
//       .attr('x', (width / 2))
//       .attr('y', 0)
//       .attr('text-anchor', 'middle')
//       .style('font-size', '16px')
//       .text(title);
//   return;
// }

// Map data into correct structure for D3
var temps = [];
var hums = [];
var setTemps = [];
var minValue = 100;
var maxValue = 0;

// Data is injected into html by server script
raw_data.forEach(function(d) {
  var time = parseTime(d[0]);
  var temp = +d[1] / 10;
  var hum = +d[2] / 10;
  var setTemp = +d[3] / 10;

  temps.push({
    time: time,
    value: temp
  });
  hums.push({
    time: time,
    value: hum
  })
  setTemps.push({
    time: time,
    value: setTemp
  })
  minValue = Math.min(minValue, temp, hum, setTemp);
  maxValue = Math.max(maxValue, temp, hum, setTemp);
});

var lastTemp = temps[0] ? temps[0].value : '';
var lastHum = hums[0] ? hums[0].value : '';
var lastSetTemp = setTemps[0] ? setTemps[0].value : '';
var lastTime = temps[0] ? temps[0].time : '';

var labels = {
  temp: 'Temperature: ' + lastTemp + '°F',
  hum: 'Humidity: ' + lastHum + '%',
  setTemp: 'Set temp: ' + lastSetTemp + '°F'
};
color.domain([labels.temp, labels.hum, labels.setTemp]);

var data = [
  {
    name: labels.temp,
    values: temps
  },
  {
    name: labels.hum,
    values: hums
  },
  {
    name: labels.setTemp,
    values: setTemps
  }
];

x.domain(d3.extent(data[0].values, function(d) { return d.time; }));
y.domain([minValue - 5, maxValue + 5]);

// Draw the axes
svg.append('g')
    .attr('class', 'x axis')
    .attr('transform', 'translate(0,' + height + ')')
    .call(xAxis);

svg.append('g')
    .attr('class', 'y axis')
    .call(yAxis)

// Draw the grid
svg.append('g')
    .attr('class', 'grid')
    .call(yAxis
        .tickSize(-width, 0, 0)
        .tickFormat('')
    )

// Draw the data
var series = svg.selectAll('.series')
    .data(data)
    .enter().append('g')
    .attr('class', 'series');

series.append('path')
    .attr('class', 'line')
    .attr('d', function(d) { return line(d.values); })
    .style('stroke', function(d) { return color(d.name); });

// Data is in reverse time order, so position text next to first item in array
if (temps.length > 0) {
  series.append('text')
      .datum(function(d) { return {name: d.name, value: d.values[0]}; })
      .attr('transform', function(d) {
        return 'translate(' + x(d.value.time) + ',' + y(d.value.value) + ')';
      })
      .attr('x', 3)
      .attr('dy', '.35em')
      .text(function(d) { return d.name; });
}

// Title and subtitles
var title = qs['title'] || 'Temperature & Humidity';
if (temps.length < 1) {
  title = 'No data to display';
}
svg.append('text')
    .attr('x', (width / 2))
    .attr('y', 0)
    .attr('text-anchor', 'middle')
    .style('font-size', '16px')
    .text(title);
svg.append('text')
    .attr('x', (width / 2))
    .attr('y', 18)
    .attr('text-anchor', 'middle')
    .style('font-size', '12px')
    .text(lastTime.toLocaleString());
var line3 = 'Heat: ' + (cur_status.heat ? 'on' : 'off') + ' - Hold: ' + (cur_status.hold ? 'on' : 'off');
svg.append('text')
    .attr('x', (width / 2))
    .attr('y', 32)
    .attr('text-anchor', 'middle')
    .style('font-size', '12px')
    .text(line3);
