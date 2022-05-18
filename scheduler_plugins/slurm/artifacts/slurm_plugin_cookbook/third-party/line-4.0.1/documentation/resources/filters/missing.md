# Examples for the missing filter

## Original file

```text
line1
line2
```

## Output file

```texttext
line1
line2
add1
add2
```

## Filter

```ruby
addlines = "add1\nadd2\n"
filter_lines '/example/missing' do
 filters(missing: [addlines, :after])
end
```
