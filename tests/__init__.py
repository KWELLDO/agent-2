"""tests 包：测试类型插件目录（类比 K8s CRD + Operator 目录）。

启动时由 cli.load_plugins("tests") 自动加载，触发 @test_type 注册。
扩展方式：在本目录新建 my_test.py，写入
    from cli import test_type

    @test_type("my_test", "自定义测试类型")
    class MyTest:
        def reconcile(self, test_case, result, ctx):
            return True, "", {"passed": 0, "total": 0}
重启后即生效。
"""
