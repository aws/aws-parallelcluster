# Examples for the before filter

## Original file

```text
line1
line2
```

## Output file

```text
line1
add1
add2
line2
```

## Filter

```ruby
addlines = "add1\nadd2\n"
filter_lines '/example/before' do
 filters(before: [/^line2$/, addlines, :last])
end
```
