-- {{< fato chave >}}: inserts the `texto` of a key from the fatos.json files listed in the
-- document header (`fatos:`, paths relative to the .qmd). No number is ever typed into a slide, so
-- a missing key, a key in two files or a missing file aborts the render instead of showing blanks.

local cache = nil

-- error() alone is not enough: when a facts file is bad, Quarto logs it and still writes the
-- HTML (exit 0). Log the message and stop the process so the render can never ship a blank number.
local function fail(msg)
  quarto.log.error(msg)
  io.stderr:write(msg .. "\n")
  os.exit(1)
end

local function dir_of(path)
  return path:match("^(.*)/[^/]*$") or "."
end

local function load_facts(meta)
  if cache then return cache end
  local files = meta["fatos"]
  if files == nil then
    fail("fato: o cabeçalho do documento não tem a lista 'fatos:'")
  end
  if pandoc.utils.type(files) ~= "List" then files = { files } end
  local base = dir_of(quarto.doc.input_file)
  local facts, origin = {}, {}
  for _, item in ipairs(files) do
    local rel = pandoc.utils.stringify(item)
    local path = rel:sub(1, 1) == "/" and rel or (base .. "/" .. rel)
    local fh = io.open(path, "r")
    if not fh then fail("fato: arquivo de fatos não existe: " .. rel .. " (" .. path .. ")") end
    local data = quarto.json.decode(fh:read("a"))
    fh:close()
    for key, fact in pairs(data["fatos"] or {}) do
      if origin[key] then
        fail("fato: a chave '" .. key .. "' aparece em dois arquivos: " .. origin[key] .. " e " .. rel)
      end
      origin[key] = rel
      facts[key] = fact
    end
  end
  cache = facts
  return facts
end

return {
  ["fato"] = function(args, kwargs, meta)
    local key = pandoc.utils.stringify(args[1] or "")
    if key == "" then fail("fato: faltou a chave: {{< fato chave >}}") end
    local fact = load_facts(meta)[key]
    if fact == nil then fail("fato: chave inexistente: " .. key) end
    if type(fact["texto"]) ~= "string" or fact["texto"] == "" then
      fail("fato: a chave '" .. key .. "' não tem o campo 'texto'")
    end
    return pandoc.Str(fact["texto"])
  end
}
