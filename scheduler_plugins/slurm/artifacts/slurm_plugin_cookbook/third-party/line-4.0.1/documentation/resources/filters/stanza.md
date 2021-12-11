# Examples for the stanza filter

## Original file

```text
[first]
  line1 = value1
[second]
  line2 = vaule2
```

## Output file

```text
[first]
  line2 = addme
  line1 = new1
[second]
  line3 = add3
  line2 = value2
```

## Filter

```ruby
filter_lines '/example/stanza' do
 filters([
   { stanza: ['first', { line1: 'new1', line2: 'addme'}] },
   { stanza: ['second', { line3: 'add3' }] },
 ])
end
```
