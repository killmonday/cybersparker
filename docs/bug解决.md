### 2026.06.27

- 问题1：扫描区域api地址错误问题修复，由于更新了前端代码需要重新build静态文件，所以重新上传docker镜像，后续有空再优化一下docker部署方案，避免重复构建。替换时，需要拉取最新的项目仓库代码（git pull），然后docker load导入镜像，这会自动更新已导入的历史镜像。然后docker-compose down 再执行 docker-compose up。

- 问题2：PoC插件目录和nuclei插件在git忽略清单，没有上传，所以docker运行报错，现在已经上传，解决办法同上，拉取最新代码和更新镜像。