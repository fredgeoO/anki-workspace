#!/usr/bin/env Rscript
# ============================================================================
# ankiR 桥 —— 由 code/analysis/ankir.py 调用（不要手跑，也不要在 PS 里传日文参数）
#
# 协议：Rscript ankir_bridge.R <request.json> <result.json>
#   request  = {"db": "<collection 副本路径>", "mode": "call"|"list",
#               "fn": "anki_report", "args": {...}, "json": true,
#               "plot_out": "...png", "width": 9, "height": 5}
#   result   = {"ok": true, "text": "...", "warnings": [...], "data_json": "..."}
#
# 三条硬约定（和 code/analysis/ankir.py 对齐）：
#   1. 只用 ankiR 的只读函数；本脚本从不写收藏库，读的永远是 Python 侧复制出来的副本。
#   2. 所有出入参走 UTF-8 文件，日文不经过命令行（Windows 下会被 codepage 吃掉）。
#   3. 结果 JSON 用 writeBin(charToRaw(enc2utf8(x))) 落地，保证是 UTF-8 字节。
# ============================================================================

args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 2L) {
  stop("usage: ankir_bridge.R <request.json> <result.json>", call. = FALSE)
}
req_path <- args[[1]]
res_path <- args[[2]]

write_result <- function(obj) {
  txt <- jsonlite::toJSON(obj, auto_unbox = TRUE, null = "null", na = "null",
                          force = TRUE, digits = NA)
  con <- file(res_path, open = "wb")
  on.exit(close(con), add = TRUE)
  writeBin(charToRaw(enc2utf8(txt)), con)
}

fail <- function(msg) {
  write_result(list(ok = FALSE, error = enc2utf8(paste(msg, collapse = " "))))
  quit(save = "no", status = 1L)
}

read_request <- function(path) {
  txt <- paste(readLines(path, warn = FALSE, encoding = "UTF-8"), collapse = "\n")
  jsonlite::fromJSON(txt, simplifyVector = FALSE)
}

req <- tryCatch(read_request(req_path), error = function(e) fail(conditionMessage(e)))
if (!is.list(req)) fail("request 不是 JSON 对象")

suppressPackageStartupMessages(library(ankiR))

# ---- mode: list —— 函数清单（名字 + Rd 标题），给技能当目录用 -----------------
if (identical(req$mode, "list")) {
  exports <- sort(getNamespaceExports("ankiR"))
  titles <- setNames(rep(NA_character_, length(exports)), exports)
  rd <- tryCatch(tools::Rd_db("ankiR"), error = function(e) NULL)
  if (!is.null(rd)) {
    for (nm in names(rd)) {
      fn <- sub("\\.Rd$", "", nm)
      if (!fn %in% exports) next
      t <- tryCatch(tools:::.Rd_get_metadata(rd[[nm]], "title"),
                    error = function(e) NA_character_)
      if (length(t)) titles[[fn]] <- gsub("\\s+", " ", paste(t, collapse = " "))
    }
  }
  write_result(list(
    ok = TRUE,
    version = as.character(utils::packageVersion("ankiR")),
    functions = lapply(exports, function(f) list(fn = f, title = titles[[f]]))
  ))
  quit(save = "no", status = 0L)
}

# ---- mode: call —— 调一个 ankiR 函数 ----------------------------------------
fn <- req$fn
if (!is.character(fn) || length(fn) != 1L || !nzchar(fn)) fail("缺少 fn")
ns <- asNamespace("ankiR")
if (!exists(fn, envir = ns, inherits = FALSE)) fail(paste0("ankiR 里没有函数：", fn))
f <- get(fn, envir = ns, inherits = FALSE)
if (!is.function(f)) fail(paste0(fn, " 不是函数"))

a <- req$args
if (is.null(a) || !is.list(a)) a <- list()
if ("path" %in% names(formals(f)) && is.null(a$path)) a$path <- req$db

warns <- character()
msgs <- character()
call_one <- function() {
  withCallingHandlers(
    do.call(f, a),
    warning = function(w) {
      warns <<- c(warns, conditionMessage(w))
      invokeRestart("muffleWarning")
    },
    message = function(m) {
      msgs <<- c(msgs, conditionMessage(m))
      invokeRestart("muffleMessage")
    }
  )
}

started <- Sys.time()
res <- NULL
txt <- tryCatch(
  capture.output({ res <- call_one() }, type = "output"),
  error = function(e) fail(paste0(fn, "() 失败：", conditionMessage(e)))
)
if (!length(txt) && !is.null(res)) {
  # 这些函数（anki_report / anki_health_check / anki_weak_areas …）不打印，只返回对象，
  # 文本模式就把返回值渲染出来：数据框截前 N 行，其余照 R 的 print。
  n_head <- req$head %||% 20L
  txt <- capture.output({
    if (is.data.frame(res)) {
      print(utils::head(res, n_head))
      if (nrow(res) > n_head) {
        cat(sprintf("... 共 %d 行（--json 取全量，--head N 改行数）\n", nrow(res)))
      }
    } else if (is.character(res) && length(res) == 1L) {
      cat(res, "\n")
    } else {
      print(res)
    }
  }, type = "output")
}

# 画图函数：结果本身是 ggplot 时才落盘（其余绘图函数直接打印到设备，见技能文档）
plot_out <- req$plot_out
if (!is.null(plot_out) && nzchar(plot_out) && inherits(res, "ggplot")) {
  ok <- tryCatch({
    ggplot2::ggsave(filename = plot_out, plot = res,
                    width = req$width %||% 9, height = req$height %||% 5,
                    dpi = 150, bg = "white")
    TRUE
  }, error = function(e) {
    warns <<- c(warns, paste0("ggsave 失败：", conditionMessage(e)))
    FALSE
  })
  if (ok) txt <- c(txt, paste0("[图已保存] ", plot_out))
}

data_json <- tryCatch(
  jsonlite::toJSON(res, auto_unbox = TRUE, null = "null", na = "null",
                   dataframe = "rows", force = TRUE, digits = NA),
  error = function(e) NULL
)

# ankiR 的 decks.name 用 \x1f 当层级分隔符（新 schema 原样返回）。它有两种面目：
# 真的控制字符（JSON 里会被转义成 \u001f）和 tibble 打印出来的字面量 "\u001f"。
# 两种都换成工作区的 `::`，文本与 JSON 两条路都换。
txt <- gsub("\\u001f", "::", txt, fixed = TRUE)
txt <- gsub("\u001f", "::", txt, fixed = TRUE)
if (!is.null(data_json)) {
  data_json <- gsub("\\u001f", "::", as.character(data_json), fixed = TRUE)
  data_json <- gsub("\u001f", "::", data_json, fixed = TRUE)
}

write_result(list(
  ok = TRUE,
  fn = fn,
  version = as.character(utils::packageVersion("ankiR")),
  seconds = round(as.numeric(difftime(Sys.time(), started, units = "secs")), 3),
  text = enc2utf8(paste(txt, collapse = "\n")),
  warnings = as.list(enc2utf8(warns)),
  messages = as.list(enc2utf8(msgs)),
  data_json = if (is.null(data_json)) NULL else as.character(data_json)
))
quit(save = "no", status = 0L)
